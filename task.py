from runpy import run_module
import numpy as np; np.set_printoptions(precision=2); np.random.seed(0)
import torch; torch.set_printoptions(precision=2)
import torch.nn as nn
import matplotlib.pyplot as plt
import matplotlib 
from matplotlib.font_manager import FontProperties
from mpl_toolkits import mplot3d

import seaborn as sns
import time
import sys
import itertools
import random; random.seed(0)
import datetime
import pickle
import copy
import pandas as pd
import scipy

from sklearn.cluster import KMeans
from sklearn.manifold import MDS
from sklearn.decomposition import PCA
from sklearn.metrics.pairwise import cosine_similarity


def get_default_hp_wcst():
    """ Default parameters for the task """
    
    hp_wcst = {
                # trial start time (in ms)
                'trial_start': 0,
                # fixation start time
                'fix_start': 0,
                # fixation end time
                'fix_end': 0,
                # trial history input start time
                'trial_history_start': 0,
                # trial history input end time
                'trial_history_end': 100,
                # stimulus start time
                'center_card_on': 1100,
                # stimulus end time
                'center_card_off': 2100,
                # response start time
                'test_cards_on': 1600,
                # response end time
                'test_cards_off': 2100,
                # response cue start time
                'resp_start': 1600,
                # response cue end time
                'resp_end': 2100,
                # trial end time
                'trial_end': 2100
                }

    return hp_wcst


    
class WCST():
    """ The Wisconsin card sorting task 
        rule list: the rules (color, shape, etc.)
        n_features_per_rule: number of features per rule (e.g. how many colors are there)
        n_test_cards: number of cards to match to the center card
    """

    def __init__(self, hp, hp_wcst, rule, rule_list, n_features_per_rule, n_test_cards):
        self.rule = rule
        self.rule_list = rule_list
        self.n_features_per_rule = n_features_per_rule
        self.n_test_cards = n_test_cards
        self.dt = hp['dt']
        self.timestamps = hp_wcst
        self.n_ts = (self.timestamps['trial_end'] - self.timestamps['trial_start'])//self.dt
        self.n_ts = int(self.n_ts)
    
        def make_task_1tr(self):
        # Generate the center card
        center_card = dict.fromkeys(self.rule_list)
        for r in self.rule_list:
            center_card[r] = random.randrange(self.n_features_per_rule)
        
        # Generate the test cards
        test_cards = dict.fromkeys(np.arange(self.n_test_cards))  
        for c in range(self.n_test_cards):
            test_cards[c] = dict.fromkeys(self.rule_list)
        
        # Define the matched features
        match_card_id = np.random.choice(np.arange(self.n_test_cards))
        test_cards[match_card_id][self.rule] = center_card[self.rule]
        
        # Define the irrelevant rules and the nonmatch card
        irrel_rules = [r for r in self.rule_list if r != self.rule]
        nonmatch_card_id = random.choice([c for c in np.arange(self.n_test_cards) if c != match_card_id])
        irrel_rule = random.choice(irrel_rules)
        test_cards[nonmatch_card_id][irrel_rule] = center_card[irrel_rule]
        
        # Define the other features
        for c in range(self.n_test_cards):
            for r in self.rule_list:
                if (c == match_card_id and r == self.rule) or (c == nonmatch_card_id and r == irrel_rule):
                    continue
                elif r == self.rule:
                    test_cards[c][r] = random.choice([f for f in range(self.n_features_per_rule) if f != center_card[r]])
                else:
                    test_cards[c][r] = random.randrange(self.n_features_per_rule)

        # Generate the input and target currents
        n_features = self.n_features_per_rule * len(self.rule_list)
        x = torch.zeros([self.n_ts, n_features * (self.n_test_cards + 1)])
        x_rule = torch.zeros([self.n_ts, len(self.rule_list)])
        yhat = torch.zeros([self.n_ts, self.n_test_cards])
        yhat_rule = torch.zeros([self.n_ts, len(self.rule_list)])
        
        # Center card
        x_idx = 0
        for r in self.rule_list:
            x[int(self.timestamps['center_card_on']//self.dt):int(self.timestamps['center_card_off']//self.dt),
            x_idx + center_card[r]] = 1
            x_idx += self.n_features_per_rule
        
        # Test cards
        for c in range(self.n_test_cards):
            for r in self.rule_list:
                x[np.arange(self.timestamps['test_cards_on']//self.dt, self.timestamps['test_cards_off']//self.dt),
                x_idx + test_cards[c][r]] = 1
                x_idx += self.n_features_per_rule
        
        # Target
        yhat[int(self.timestamps['resp_start']//self.dt):int(self.timestamps['resp_end']//self.dt), match_card_id] = 1
        rule_idx = self.rule_list.index(self.rule)
        yhat_rule[int(self.timestamps['trial_start']//self.dt):int(self.timestamps['trial_end']//self.dt), rule_idx] = 1

        # Other information about this trial
        task_data = {'center_card': center_card, 'test_cards': test_cards, 'correct_id': match_card_id}
        
        return x, x_rule, yhat, yhat_rule, task_data
        
    
    def make_task_batch(self, batch_size):
        x = []
        x_rule = []
        yhat = []
        yhat_rule = []
        task_data = []
        for ba in range(batch_size):
            _x, _x_rule, _yhat, _yhat_rule, _task_data = self.make_task_1tr()
            x.append(_x)
            yhat.append(_yhat)
            yhat_rule.append(_yhat_rule)
            task_data.append(_task_data)
        x = torch.stack(x, dim=1)
        x_rule = torch.tensor(x_rule)
        yhat = torch.stack(yhat, dim=1)
        yhat_rule = torch.stack(yhat_rule, dim=1)

        return x, x_rule, yhat, yhat_rule, task_data
    
    
    def get_perf(self, y, yhat):
        """ From the output and target, get the performance of the network 
            Args:
                y: batch_size*n_output*n_timesteps.
                yhat: batch_size*n_output*n_timesteps.
            Returns:
                resp_correct: length batch_size binary vector
        """
#         print(y.shape, yhat.shape, flush=True)
        if y.size()[-1]!=3 or yhat.size()[-1]!=3:
            raise ValueError('This function only works when there are 3 choices!')
            
        resp_start_ts = int(self.timestamps['resp_start']/self.dt)
        resp_end_ts = int(self.timestamps['resp_end']/self.dt)

#         softmax = nn.Softmax(dim=1)    # softmax would soften the difference a lot and worsen the performance...

        y_choice = torch.mean(y[resp_start_ts:resp_end_ts, :, :], dim=0)    # the mean network output during choice period
        choice_prob = y_choice    # convert output into choice probability        
        choice = torch.zeros([choice_prob.shape[0], 3]).to(choice_prob.device)    # compute choices from choice probabilities
        
        # winner take all
        for j in range(choice.shape[1]):
            choice[:,j] = torch.tensor([1 if choice_prob[i, j]==torch.max(choice_prob[i, :]) else 0 for i in range(choice_prob.shape[0])])    # the maximum of the three outputs is the choice
        
        # alternatively, sample a choice using output neurons' activity
#         for i in range(choice.shape[0]):
# #             choice_prob_norm = (choice_prob[i, :]/torch.sum(choice_prob[i, :])).numpy()
#             choice_prob_norm = torch.softmax(choice_prob[i, :]/0.4, dim=0).numpy()
#             if i==0:
#                 print('choice_prob_norm = {}'.format(choice_prob_norm))
#             j = np.random.choice([0, 1, 2], size=1, p=choice_prob_norm)
#             choice[i, j] = 1        
        
        
        target = torch.mean(yhat[resp_start_ts:resp_end_ts, :, :], dim=0)
        target_prob = target

    #     print('choice device: {}. target_prob device: {}'.format(choice.device, target_prob.device))
#         match = torch.abs(choice - target_prob) <= 0.5     # correct when the   
    #     match = torch.abs(choice_prob - target_prob) <= 0.5    # to prevent low activity for both output nodes
        match = (choice==target_prob)
        resp_correct = match[:,0] * match[:,1] * match[:,2]    # correct response if the probability from target is differed by less than threshold% for both choices

        return resp_correct, choice_prob, choice
    
    
    def get_perf_rule(self, y_rule, yhat_rule):
        """ Get the performance of the network for the rule output
            Args:
                y: batch_size*n_output*n_timesteps. default n_output=2
                yhat: batch_size*n_output*n_timesteps. default n_output=2
            Returns:
                resp_correct: length batch_size binary vector
        """
#         print(y.shape, yhat.shape, flush=True)
        if y_rule.size()[-1]!=2 or yhat_rule.size()[-1]!=2:
            raise ValueError('This function only works when there are 2 rules!')
            
        rule_start_ts = int(self.timestamps['trial_start']/self.dt)
        rule_end_ts = int(self.timestamps['trial_end']/self.dt)
        
#         softmax = nn.Softmax(dim=1)    # softmax would soften the difference a lot and worsen the performance...

        y_choice = torch.mean(y_rule[rule_start_ts:rule_end_ts, :, :], dim=0)    # the mean network output during choice period
        choice_prob = y_choice    # convert output into choice probability        
        choice = torch.zeros([choice_prob.shape[0], 2]).to(choice_prob.device)    # compute choices from choice probabilities
        for j in range(choice.shape[1]):
            choice[:, j] = torch.tensor([1 if choice_prob[i, j]==torch.max(choice_prob[i, :]) else 0 for i in range(choice_prob.shape[0])])    # the maximum of the outputs is the choice
        
        target = torch.mean(yhat_rule[rule_start_ts:rule_end_ts, :, :], dim=0)
    #     print('choice device: {}. target_prob device: {}'.format(choice.device, target_prob.device))
#         match = torch.abs(choice - target_prob) <= 0.5     # correct when the   
    #     match = torch.abs(choice_prob - target_prob) <= 0.5    # to prevent low activity for both output nodes
        _match = (choice==target)
        match = _match[:,0] * _match[:,1]    # correct response if the probability from target is differed by less than threshold% for both choices
        
        # alternatively
#         match = torch.tensor([choice[i, :]==target[i, :] for i in choice.shape[0]])

        return match, choice_prob, choice



    






    



