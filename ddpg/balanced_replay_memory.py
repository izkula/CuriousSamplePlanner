import random
from collections import namedtuple
import numpy as np
from CuriousSamplePlanner.scripts.utils import *

# Taken from
# https://github.com/pytorch/tutorials/blob/master/Reinforcement%20(Q-)Learning%20with%20PyTorch.ipynb

Transition = namedtuple(
    'Transition', ('state', 'action', 'mask', 'next_state', 'reward'))


class BalancedReplayMemory(object):

    def __init__(self, capacity, num_classes = 2, split=0.2):
        self.capacity = capacity
        self.split = split
        self.memory_banks = [[] for _ in range(num_classes)]

    def push(self, class_index, *args):
        # print("Fail: "+str(len(self.memory_banks[0]))+" Success: "+str(len(self.memory_banks[1])))
        """Saves a transition."""

        if len(self.memory_banks[class_index]) > self.capacity:
            del self.memory_banks[class_index][0]
        self.memory_banks[class_index].append(Transition(*args))


    def sample(self, batch_size):
        print(len(self.memory_banks[0]))
        print(len(self.memory_banks[1]))
        returning = []
        for _ in range(batch_size):
            index = np.random.choice(np.arange(len(self.memory_banks)), p=[1-self.split, self.split])
            if(len(self.memory_banks[index]) > 0):
                returning.append(random.choice(self.memory_banks[index]))
            else:
                returning.append(random.choice(self.memory_banks[1-index]))


        
        return returning

    def __len__(self):
        return sum([len(i) for i in self.memory_banks])
