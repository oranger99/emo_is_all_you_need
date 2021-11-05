import ipdb
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import BertPreTrainedModel, BertTokenizer, BertConfig, BertModel
import config
import numpy as np

class EmotionClassifier(nn.Module):
    def __init__(self, n_classes, bert):
        super(EmotionClassifier, self).__init__()
        self.bert = bert
        self.fc = nn.Linear(self.bert.config.hidden_size, n_classes)
        self.sigmod = nn.Sigmoid()

    def forward(self, input_ids, attention_mask):
        _, pooled_output = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            return_dict = False
        )
        out = self.fc(pooled_output)
        out = self.sigmod(out)
        
        # ipdb.set_trace()
        return out

if __name__ == "__main__":
    base_model = BertModel.from_pretrained(config.PRE_TRAINED_MODEL_NAME)  # 加载预训练模型
    model = EmotionClassifier(n_classes=4, bert=base_model)

    input_ids = torch.randint(1, 10000, (256,1)).squeeze(1).unsqueeze(0)
    attention_mask = torch.Tensor([1 for i in range(256)]).unsqueeze(0)
    # ipdb.set_trace()
    print(input_ids.shape)
    print(attention_mask.shape)
    output = model(input_ids, attention_mask)
    print(output.shape)