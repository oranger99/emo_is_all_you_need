from re import M
import torch
import torch.nn as nn
from transformers import BertPreTrainedModel, BertTokenizer, BertConfig, BertModel
from transformers import AdamW, get_linear_schedule_with_warmup
from torch.utils.tensorboard import SummaryWriter
from torch.utils.data import DataLoader
import math

#import os
#os.environ["CUDA_VISIBLE_DEVICES"] = '3'
import numpy as np
import time
import ipdb

from roledataset import RoleDataset, create_dataloader
from model import EmotionClassifier
from utils import load_checkpoint, save_checkpoint
from predict import predict, validate
from adv_train import FGM, grad_test
import config
from classiloss import ClassiLoss


# roberta
#PRE_TRAINED_MODEL_NAME='hfl/chinese-roberta-wwm-ext'
tokenizer = BertTokenizer.from_pretrained(config.PRE_TRAINED_MODEL_NAME)
base_model = BertModel.from_pretrained(config.PRE_TRAINED_MODEL_NAME)  # 加载预训练模型
# model = ppnlp.transformers.BertForSequenceClassification.from_pretrained(MODEL_NAME, num_classes=2)

trainset = RoleDataset(tokenizer, config.max_len, mode='train')

train_size = int(len(trainset) * 0.95)
validate_size = len(trainset) - train_size

train_dataset, validate_dataset = torch.utils.data.random_split(trainset, [train_size, validate_size])
train_loader = create_dataloader(train_dataset, config.batch_size, mode='train')
validate_loader = DataLoader(validate_dataset, config.batch_size, shuffle=False)

#train_loader = create_dataloader(trainset, config.batch_size, mode='train')
test_dataset = RoleDataset(tokenizer, config.max_len, mode='test')
test_loader = DataLoader(test_dataset, config.batch_size, shuffle=False)

model = EmotionClassifier(n_classes=1, bert=base_model).to(config.device)
# print(model)
# ipdb.set_trace()
optimizer = AdamW(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)
if config.load_model:
    load_checkpoint(torch.load(config.model_root), model, optimizer)

total_steps = len(train_loader) * config.EPOCH_NUM

scheduler = get_linear_schedule_with_warmup(
  optimizer,
  num_warmup_steps = config.warm_up_ratio * total_steps,
  num_training_steps = total_steps
)

criterion = ClassiLoss()

writer = SummaryWriter(config.run_plot)

fgm = FGM(model)

def do_train(model, date_loader, criterion, optimizer, scheduler, metric=None):
    model.train()
    tic_train = time.time()
    log_steps = 1
    global_step = 0
    for epoch in range(config.EPOCH_NUM):
        losses = []
        for step, sample in enumerate(train_loader):
            if step == 3:
                break
            input_ids = sample["input_ids"].to(config.device)
            # print(tokenizer.decode(input_ids[0]))
            attention_mask = sample["attention_mask"].to(config.device)

            target = None
            #ipdb.set_trace()
            for col in config.target_cols:
                if target == None:
                    target = sample[col].unsqueeze(1).to(config.device)
                else:
                    target = torch.cat((target, sample[col].unsqueeze(1).to(config.device)), dim=1)

            
            # 1. 正常训练
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)             
         
            # ipdb.set_trace() 
            # outputs = torch.argmax(outputs, axis=2) # [64, 6, 4] ->  [64, 6]
            loss = criterion(outputs, target) # outputs有梯度，target没有梯度，loss有梯度
            # print(loss)
            # ipdb.set_trace()
            losses.append(loss.item())

            loss.backward()  # 反向传播，得到正常的grad
            grad_test(model)  # 查看是否有梯度

            # 2. 对抗训练
            fgm.attack(epsilon=0.3, emb_name='word_embeddings')
            outputs_adv = model(input_ids=input_ids, attention_mask=attention_mask)
            loss_adv = criterion(outputs_adv, target)
            loss_adv.backward()
            fgm.restore(emb_name='word_embeddings')

#             nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            scheduler.step()

            optimizer.zero_grad()
            

            global_step += 1

            if global_step % log_steps == 0:
                print("global step %d, epoch: %d, batch: %d, loss: %.5f, speed: %.2f step/s, lr: %.10f"
                      % (global_step, epoch, step, loss, global_step / (time.time() - tic_train), 
                         float(scheduler.get_last_lr()[0])))

            writer.add_scalar("Training loss", loss, global_step=global_step)

        # 每一轮epoch
        # save model
        if config.save_model:
            checkpoint = {
                "state_dict": model.state_dict(),
                "optimizer": optimizer.state_dict(),
            }
            save_checkpoint(checkpoint, filename=config.model_root)

        # 验证
        model.eval()
        validate_pred = validate(model, validate_loader)
        print("score: %f" % (validate_pred))
        print("score: %f" % (1/(1+math.sqrt(validate_pred))))

    #评估
    model.eval()
    predict(model, test_loader)


do_train(model, train_loader, criterion, optimizer, scheduler)
