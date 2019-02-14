"""

Reference  https://github.com/Zhenye-Na/DA-RNN

"""
from ops import *
from torch.autograd import Variable

import torch
from torch import cuda
# torch.cuda.is_available()
import numpy as np
from torch import nn
from torch import optim
import torch.nn.functional as F
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt




class Encoder(nn.Module):
    """encoder in DA_RNN."""

    def __init__(self, T,
                 input_size,
                 encoder_num_hidden,
                 parallel=False):
        """Initialize an encoder in DA_RNN."""
        super(Encoder, self).__init__()
        self.encoder_num_hidden = encoder_num_hidden
        self.input_size = input_size
        self.parallel = parallel
        self.T = T

        
        self.encoder_lstm = nn.LSTM(
            input_size=self.input_size, hidden_size=self.encoder_num_hidden)

       
        self.encoder_attn = nn.Linear(
            in_features=2 * self.encoder_num_hidden + self.T - 1, out_features=1, bias=True)

    def forward(self, X):
        
        X_tilde = Variable(X.data.new(
            X.size(0), self.T - 1, self.input_size).zero_())
        X_encoded = Variable(X.data.new(
            X.size(0), self.T - 1, self.encoder_num_hidden).zero_())

        
        h_n = self._init_states(X)
        s_n = self._init_states(X)

        for t in range(self.T - 1):
            # batch_size * input_size * (2*hidden_size + T - 1)
            x = torch.cat((h_n.repeat(self.input_size, 1, 1).permute(1, 0, 2),
                           s_n.repeat(self.input_size, 1, 1).permute(1, 0, 2),
                           X.permute(0, 2, 1)), dim=2)

            x = self.encoder_attn(
                x.view(-1, self.encoder_num_hidden * 2 + self.T - 1))

            
            alpha = F.softmax(x.view(-1, self.input_size))

            
            x_tilde = torch.mul(alpha, X[:, t, :])

            
            self.encoder_lstm.flatten_parameters()
            _, final_state = self.encoder_lstm(
                x_tilde.unsqueeze(0), (h_n, s_n))
            h_n = final_state[0]
            s_n = final_state[1]

            X_tilde[:, t, :] = x_tilde
            X_encoded[:, t, :] = h_n

        return X_tilde, X_encoded

    def _init_states(self, X):
       
        
        initial_states = Variable(X.data.new(
            1, X.size(0), self.encoder_num_hidden).zero_())
        return initial_states


class Decoder(nn.Module):
    

    def __init__(self, T, decoder_num_hidden, encoder_num_hidden):
        """Initialize a decoder in DA_RNN."""
        super(Decoder, self).__init__()
        self.decoder_num_hidden = decoder_num_hidden
        self.encoder_num_hidden = encoder_num_hidden
        self.T = T

        self.attn_layer = nn.Sequential(nn.Linear(2 * decoder_num_hidden + encoder_num_hidden, encoder_num_hidden),
                                        nn.Tanh(),
                                        nn.Linear(encoder_num_hidden, 1))
        self.lstm_layer = nn.LSTM(
            input_size=1, hidden_size=decoder_num_hidden)
        self.fc = nn.Linear(encoder_num_hidden + 1, 1)
        self.fc_final_price = nn.Linear(decoder_num_hidden + encoder_num_hidden, 1) #for price
        self.fc_final_trend = nn.Linear(decoder_num_hidden + encoder_num_hidden, 3) #for trend
        self.fc_final_trade = nn.Linear(decoder_num_hidden + encoder_num_hidden, 3) #for trade

        self.fc.weight.data.normal_()

    def forward(self, X_encoed, y_prev):
       
        d_n = self._init_states(X_encoed)
        c_n = self._init_states(X_encoed)

        for t in range(self.T - 1):

            x = torch.cat((d_n.repeat(self.T - 1, 1, 1).permute(1, 0, 2),
                           c_n.repeat(self.T - 1, 1, 1).permute(1, 0, 2),
                           X_encoed), dim=2)

            beta = F.softmax(self.attn_layer(
                x.view(-1, 2 * self.decoder_num_hidden + self.encoder_num_hidden)).view(-1, self.T - 1))
            
            context = torch.bmm(beta.unsqueeze(1), X_encoed)[:, 0, :]
            if t < self.T - 1:
                
                y_tilde = self.fc(
                    torch.cat((context, y_prev[:, t].unsqueeze(1)), dim=1))
                
                self.lstm_layer.flatten_parameters()
                _, final_states = self.lstm_layer(
                    y_tilde.unsqueeze(0), (d_n, c_n))
               
                d_n = final_states[0]
             
                c_n = final_states[1]
        
        final_temp_y = torch.cat((d_n[0], context), dim=1)
        y_pred_price = self.fc_final_price(final_temp_y)
        y_pred_trend = F.softmax(self.fc_final_trend(final_temp_y))
        y_pred_trade = F.softmax(self.fc_final_trade(final_temp_y))
        return y_pred_price, y_pred_trend, y_pred_trade

    def _init_states(self, X):
       
        
        initial_states = X.data.new(
            1, X.size(0), self.decoder_num_hidden).zero_()
        return initial_states



class DA_rnn(nn.Module):
    """da_rnn."""

    def __init__(self, X, y, trade, trend, T,
                 encoder_num_hidden,
                 decoder_num_hidden,
                 batch_size,
                 learning_rate,
                 epochs,
                 parallel=False):
       
        super(DA_rnn, self).__init__()
        self.encoder_num_hidden = encoder_num_hidden
        self.decoder_num_hidden = decoder_num_hidden
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.parallel = parallel
        self.shuffle = False
        self.epochs = epochs
        self.T = T
        self.X = X
        self.y = y
        self.trade = trade
        self.trend = trend

        self.Encoder = Encoder(input_size=X.shape[1],
                               encoder_num_hidden=encoder_num_hidden,
                               T=T)
        self.Decoder = Decoder(encoder_num_hidden=encoder_num_hidden,
                               decoder_num_hidden=decoder_num_hidden,
                               T=T)
        # self.Encoder = self.Encoder.cuda()
        # self.Decoder = self.Decoder.cuda()
        # Loss function
        self.criterion_price = nn.MSELoss()
        self.criterion_trend = nn.CrossEntropyLoss()
        self.criterion_trade = nn.CrossEntropyLoss()

        if self.parallel:
            self.encoder = nn.DataParallel(self.encoder)
            self.decoder = nn.DataParallel(self.decoder)

        self.encoder_optimizer = optim.Adam(params=filter(lambda p: p.requires_grad,
                                                          self.Encoder.parameters()),
                                            lr=self.learning_rate)
        self.decoder_optimizer = optim.Adam(params=filter(lambda p: p.requires_grad,
                                                          self.Decoder.parameters()),
                                            lr=self.learning_rate)
        
        
        self.train_timesteps = int(self.X[:243].shape[0]) 
        self.input_size = self.X.shape[1]

    def train(self):
       
        iter_per_epoch = int(np.ceil(self.train_timesteps * 1. / self.batch_size))
        self.iter_losses = np.zeros(self.epochs * iter_per_epoch)
        self.epoch_losses = np.zeros(self.epochs)
        
        n_iter = 0
        
        for epoch in range(self.epochs):
            if self.shuffle:
                ref_idx = np.random.permutation(self.train_timesteps - self.T)
            else:
                ref_idx = np.array(range(self.train_timesteps - self.T))

            idx = 0

            while (idx < self.train_timesteps):
               
                indices = ref_idx[idx:(idx + self.batch_size)]
               
                x = np.zeros((len(indices), self.T - 1, self.input_size))
                y_prev = np.zeros((len(indices), self.T - 1))
                y_gt = self.y[indices + self.T]
                trade_gt = self.trade[indices + self.T]
                trend_gt = self.trend[indices + self.T]
                
                for bs in range(len(indices)):
                    x[bs, :, :] = self.X[indices[bs]:(indices[bs] + self.T - 1), :]
                    y_prev[bs, :] = self.y[indices[bs]:(indices[bs] + self.T - 1)]
                   

                loss = self.train_forward(x, y_prev, y_gt,trend_gt,trade_gt)
                

                self.iter_losses[epoch * iter_per_epoch + idx // self.batch_size] = loss
                

                idx += self.batch_size
                n_iter += 1

                if n_iter % 4000 == 0 and n_iter != 0:
                    for param_group in self.encoder_optimizer.param_groups:
                        param_group['lr'] = param_group['lr'] * 0.8
                    for param_group in self.decoder_optimizer.param_groups:
                        param_group['lr'] = param_group['lr'] * 0.8

                self.epoch_losses[epoch] = np.mean(self.iter_losses[range(epoch * iter_per_epoch, (epoch + 1) * iter_per_epoch)])
                
            if epoch % 10 == 0:
                print ("Epochs: ", epoch, " Iterations: ", n_iter, " Loss: ", self.epoch_losses[epoch])
                

            
                



    def train_forward(self, X, y_prev, y_gt,trend_gt,trade_gt):
        
        self.encoder_optimizer.zero_grad()
        self.decoder_optimizer.zero_grad()

        input_weighted, input_encoded = self.Encoder(
            Variable(torch.from_numpy(X).type(torch.FloatTensor))) #cuda
        y_pred_price, y_pred_trend, y_pred_trade = self.Decoder(input_encoded, Variable(
            torch.from_numpy(y_prev).type(torch.FloatTensor)))#cuda
        # print(y_pred_trade)
        y_true_price = torch.from_numpy(
            y_gt).type(torch.FloatTensor)
        y_true_price =y_true_price.view(-1, 1) #cuda
        
        
        y_true_trend = torch.from_numpy(
            trend_gt).type(torch.LongTensor)
    
        y_true_trade = torch.from_numpy(
            trade_gt).type(torch.LongTensor)
        
        
        # print(y_pred_trend)
        # print(y_true_trend)
        loss1 = self.criterion_price(y_pred_price, y_true_price)
        loss2 = self.criterion_trend(y_pred_trend, y_true_trend)
        loss3 = self.criterion_trade(y_pred_trade, y_true_trade)
        # loss_total = loss+loss2+loss3
        loss = loss1+loss2+loss3 
        loss.backward()
        
        
       
        self.encoder_optimizer.step()
        self.decoder_optimizer.step()
        

        return loss.item()
       

    

    def val(self):
        """validation."""
        pass




    def test(self, on_train=False):
        """test."""

        if on_train:
            y_pred_price = np.zeros(self.train_timesteps - self.T + 1)
            y_pred_trend = np.zeros(self.train_timesteps - self.T + 1)
            y_pred_trade = np.zeros(self.train_timesteps - self.T + 1)
            # print(len(y_pred_price)) #234
            # print(self.T)#10
        else:
            y_pred_price = np.zeros(self.X.shape[0] - self.train_timesteps)
            y_pred_trend = np.zeros(self.X.shape[0] - self.train_timesteps)
            y_pred_trade = np.zeros(self.X.shape[0] - self.train_timesteps)


        i = 0
        while i < len(y_pred_price):
            batch_idx = np.array(range(len(y_pred_price)))[i : (i + self.batch_size)]
            # print(batch_idx)
            X = np.zeros((len(batch_idx), self.T - 1, self.X.shape[1]))
            y_history = np.zeros((len(batch_idx), self.T - 1))
            for j in range(len(batch_idx)):
                if on_train:
                    X[j, :, :] = self.X[range(batch_idx[j], batch_idx[j] + self.T - 1), :]
                    y_history[j, :] = self.y[range(batch_idx[j],  batch_idx[j]+ self.T - 1)]
                else:

                    X[j, :, :] = self.X[range(batch_idx[j] + self.train_timesteps - self.T, batch_idx[j] + self.train_timesteps - 1), :]
                    y_history[j, :] = self.y[range(batch_idx[j] + self.train_timesteps - self.T,  batch_idx[j]+ self.train_timesteps - 1)]

            y_history = Variable(torch.from_numpy(y_history).type(torch.FloatTensor))
            _, input_encoded = self.Encoder(Variable(torch.from_numpy(X).type(torch.FloatTensor)))
            # y_pred[i:(i + self.batch_size)] = self.Decoder(input_encoded, y_history).cpu().data.numpy()[:, 0]
            y_pred_price, y_pred_trend, y_pred_trade = self.Decoder(input_encoded, y_history)

            y_pred_price = y_pred_price[i:(i + self.batch_size)]
            y_pred_price = y_pred_price.cpu().detach().numpy()[:, 0]
            # y_pred_trend =  y_pred_trend[i:(i + self.batch_size)]
            # y_pred_trend =  y_pred_trend.cpu().detach().numpy()[:, 0]
            # y_pred_trade = y_pred_trade[i:(i + self.batch_size)]
            # y_pred_trade = y_pred_trade.cpu().detach().numpy()[:, 0]
            
            
            i += self.batch_size
        return y_pred_price , torch.max(y_pred_trade,1)[1] , torch.max(y_pred_trend,1)[1]


    # def pre():
        
