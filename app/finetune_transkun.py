"""Fine-tune Transkun model from pretrained weights.

Loads the pretrained 2.0.pt state_dict and fine-tunes on MAESTRO data
with a lower learning rate and data augmentation.
"""
import os
import sys
import random
import copy
import time
import math
import argparse
import numpy as np
import torch
import torch_optimizer as optim
from torch.utils.tensorboard import SummaryWriter

import moduleconf
from transkun import Data
from transkun.TrainUtil import (
    initializeCheckpoint, save_checkpoint, doValidation,
    getOptimizerGroup, MovingBuffer, load_state_dict_tolerant
)


def finetune(args):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    torch.cuda.set_device(device)
    random.seed(int(time.time()))
    np.random.seed(int(time.time()))
    torch.manual_seed(int(time.time()))
    torch.cuda.manual_seed(int(time.time()))

    # Allow TF32 for faster training
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    # Load model config
    confManager = moduleconf.parseFromFile(args.modelConf)
    TransKun = confManager["Model"].module.TransKun
    conf = confManager["Model"].config

    # Create model and load pretrained weights
    print("Creating model from config...")
    model = TransKun(conf=conf).to(device)

    print(f"Loading pretrained weights from {args.pretrained}...")
    pretrained = torch.load(args.pretrained, map_location=device)
    if 'state_dict' in pretrained:
        state_dict = pretrained['state_dict']
    else:
        state_dict = pretrained

    # Load with tolerance (ignore mismatched keys)
    load_state_dict_tolerant(model, state_dict)
    print("Pretrained weights loaded successfully!")

    # Setup optimizer with lower LR for fine-tuning
    optimizerGroup = getOptimizerGroup(model)
    optimizer = optim.AdaBelief(
        optimizerGroup,
        args.max_lr,
        weight_decouple=True,
        eps=1e-8,
        weight_decay=args.weight_decay,
        rectify=True
    )

    # LR scheduler
    lrScheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, args.max_lr, args.nIter,
        pct_start=0.05, cycle_momentum=False,
        final_div_factor=2, div_factor=20
    )

    best_state_dict = copy.deepcopy(model.state_dict())
    lossTracker = {'train': [], 'val': []}
    startEpoch = 0
    startIter = 0

    # Save initial checkpoint (so we can resume)
    save_checkpoint(args.output, startEpoch, startIter, model,
                    lossTracker, best_state_dict, optimizer, lrScheduler)
    print("Initial checkpoint saved.")

    # Load dataset
    print("Loading dataset...")
    dataset = Data.DatasetMaestro(args.datasetPath, args.datasetMetaFile_train)
    datasetVal = Data.DatasetMaestro(args.datasetPath, args.datasetMetaFile_val)
    print("Dataset loaded.")

    writer = SummaryWriter(args.output + ".log")
    globalStep = startIter

    batchSize = args.batchSize
    hopSize = conf.segmentHopSizeInSecond
    chunkSize = conf.segmentSizeInSecond

    gradNormHist = MovingBuffer(initValue=40, maxLen=10000)

    augmentator = None
    if args.augment:
        augmentator = Data.AugmentatorAudiomentations(
            sampleRate=44100,
            noiseFolder=args.noiseFolder,
            convIRFolder=args.irFolder
        )

    for epoc in range(startEpoch, 1000000):
        dataIter = Data.DatasetMaestroIterator(
            dataset, hopSize, chunkSize,
            seed=epoc * 100 + 42,
            augmentator=augmentator,
            notesStrictlyContained=False
        )

        dl_kwargs = dict(
            batch_size=batchSize,
            collate_fn=Data.collate_fn_batching,
            num_workers=args.dataLoaderWorkers,
            shuffle=True,
            drop_last=True
        )
        if args.dataLoaderWorkers > 0:
            dl_kwargs['prefetch_factor'] = max(4, args.dataLoaderWorkers)
        dataloader = torch.utils.data.DataLoader(dataIter, **dl_kwargs)

        lossAll = []
        globalStepWarmupCutoff = globalStep + 500

        for idx, batch in enumerate(dataloader):
            currentLR = [p["lr"] for p in optimizer.param_groups][0]
            writer.add_scalar('Optimizer/lr', currentLR, globalStep)

            computeStats = (idx % 40 == 0)

            t1 = time.time()
            model.train()
            optimizer.zero_grad()

            totalBatch = torch.zeros(1).cuda()
            totalLoss = torch.zeros(1).cuda()
            totalLen = torch.zeros(1).cuda()

            totalGT = torch.zeros(1).cuda()
            totalEst = torch.zeros(1).cuda()
            totalCorrect = torch.zeros(1).cuda()
            totalGTFramewise = torch.zeros(1).cuda()
            totalEstFramewise = torch.zeros(1).cuda()
            totalCorrectFramewise = torch.zeros(1).cuda()
            totalSEVelocity = torch.zeros(1).cuda()
            totalSEOF = torch.zeros(1).cuda()

            notesBatch = batch["notes"]
            audioSlices = batch["audioSlices"].to(device)
            audioLength = audioSlices.shape[1] / model.conf.fs

            logp = model.log_prob(audioSlices, notesBatch)
            loss = (-logp.sum(-1).mean())

            (loss / 50).backward()

            totalBatch = totalBatch + 1
            totalLen = totalLen + audioLength
            totalLoss = totalLoss + loss.detach()

            if computeStats:
                with torch.no_grad():
                    model.eval()
                    stats = model.computeStats(audioSlices, notesBatch)
                    stats2 = model.computeStatsMIREVAL(audioSlices, notesBatch)

                totalGT = totalGT + stats2["nGT"]
                totalEst = totalEst + stats2["nEst"]
                totalCorrect = totalCorrect + stats2["nCorrect"]
                totalGTFramewise = totalGTFramewise + stats["nGTFramewise"]
                totalEstFramewise = totalEstFramewise + stats["nEstFramewise"]
                totalCorrectFramewise = totalCorrectFramewise + stats["nCorrectFramewise"]
                totalSEVelocity = totalSEVelocity + stats["seVelocityForced"]
                totalSEOF = totalSEOF + stats["seOFForced"]

            loss = totalLoss / totalLen
            curClipValue = gradNormHist.getQuantile(args.gradClippingQuantile)
            totalNorm = torch.nn.utils.clip_grad_norm_(model.parameters(), curClipValue)
            gradNormHist.step(totalNorm.item())
            optimizer.step()

            try:
                if globalStep > globalStepWarmupCutoff:
                    lrScheduler.step()
            except:
                pass

            t2 = time.time()
            print(f"epoch:{epoc} progress:{idx/len(dataloader):.3f} step:{globalStep} "
                  f"loss:{loss.item():.4f} gradNorm:{totalNorm.item():.2f} "
                  f"clipValue:{curClipValue:.2f} time:{t2-t1:.2f}")

            writer.add_scalar('Loss/train', loss.item(), globalStep)
            writer.add_scalar('Optimizer/gradNorm', totalNorm.item(), globalStep)
            writer.add_scalar('Optimizer/clipValue', curClipValue, globalStep)

            if computeStats:
                nGT = totalGT.item() + 1e-4
                nEst = totalEst.item() + 1e-4
                nCorrect = totalCorrect.item() + 1e-4
                precision = nCorrect / nEst
                recall = nCorrect / nGT
                f1 = 2 * precision * recall / (precision + recall)
                print(f"  f1:{f1:.4f} precision:{precision:.4f} recall:{recall:.4f}")
                writer.add_scalar('Loss/train_f1', f1, globalStep)

            if math.isnan(loss.item()):
                print("NaN loss detected, stopping!")
                exit()

            lossAll.append(loss.item())

            # Save every 2000 steps
            if idx % 2000 == 1999:
                save_checkpoint(args.output, epoc + 1, globalStep + 1, model,
                                lossTracker, best_state_dict, optimizer, lrScheduler)
                print("Checkpoint saved.")

            globalStep += 1

        # Validation
        print("Validating...")
        torch.cuda.empty_cache()

        dataIterVal = Data.DatasetMaestroIterator(
            datasetVal,
            hopSizeInSecond=conf.segmentHopSizeInSecond,
            chunkSizeInSecond=chunkSize,
            notesStrictlyContained=False,
            seed=42 + epoc * 100
        )
        dataloaderVal = torch.utils.data.DataLoader(
            dataIterVal, batch_size=2 * batchSize,
            collate_fn=Data.collate_fn,
            num_workers=args.dataLoaderWorkers,
            shuffle=True
        )

        model.eval()
        valResult = doValidation(model, dataloaderVal, parallel=False, device=device)

        nll = valResult["meanNLL"]
        f1 = valResult["f1"]
        torch.cuda.empty_cache()

        lossAveraged = sum(lossAll) / len(lossAll)
        lossAll = []
        lossTracker['train'].append(lossAveraged)
        lossTracker['val'].append(f1)

        print(f'Validation result: {valResult}')

        for key in valResult:
            writer.add_scalar('val/' + key, valResult[key], epoc)

        if f1 >= max(lossTracker['val']) * 1.00:
            print('Best model updated!')
            best_state_dict = copy.deepcopy(model.state_dict())

        save_checkpoint(args.output, epoc + 1, globalStep + 1, model,
                        lossTracker, best_state_dict, optimizer, lrScheduler)
        print(f"Epoch {epoc} complete. Checkpoint saved.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser("Fine-tune Transkun from pretrained weights")
    parser.add_argument('--pretrained', required=True,
                        help="Path to pretrained model state_dict (e.g. 2.0.pt)")
    parser.add_argument('--output', required=True,
                        help="Output checkpoint path")
    parser.add_argument('--modelConf', required=True,
                        help="Path to model config file (e.g. 2.0.conf)")
    parser.add_argument('--datasetPath', required=True)
    parser.add_argument('--datasetMetaFile_train', required=True)
    parser.add_argument('--datasetMetaFile_val', required=True)
    parser.add_argument('--batchSize', default=4, type=int)
    parser.add_argument('--max_lr', default=5e-5, type=float,
                        help="Max learning rate (lower for fine-tuning)")
    parser.add_argument('--weight_decay', default=1e-4, type=float)
    parser.add_argument('--nIter', default=10000, type=int)
    parser.add_argument('--dataLoaderWorkers', default=0, type=int)
    parser.add_argument('--gradClippingQuantile', default=0.8, type=float)
    parser.add_argument('--augment', action='store_true')
    parser.add_argument('--noiseFolder', required=False, default=None)
    parser.add_argument('--irFolder', required=False, default=None)

    args = parser.parse_args()
    finetune(args)
