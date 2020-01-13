import copy
import glob
import os
import time
from collections import deque
import gym
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from CuriousSamplePlanner.rl_ppo_rnd.a2c_ppo_acktr import algo, utils
from CuriousSamplePlanner.rl_ppo_rnd.a2c_ppo_acktr.model import Policy
from CuriousSamplePlanner.rl_ppo_rnd.a2c_ppo_acktr.storage import RolloutStorage
from gym import spaces
from CuriousSamplePlanner.scripts.utils import *
from CuriousSamplePlanner.trainers.architectures import DynamicsModel

import pickle
import shutil
from CuriousSamplePlanner.tasks.three_block_stack import ThreeBlocks
from CuriousSamplePlanner.tasks.five_block_stack import FiveBlocks
from CuriousSamplePlanner.tasks.ball_ramp import BallRamp
from CuriousSamplePlanner.tasks.bookshelf import BookShelf
from CuriousSamplePlanner.tasks.pulley import PulleySeesaw
from CuriousSamplePlanner.trainers.dataset import ExperienceReplayBuffer

# RL-Related Imports
from CuriousSamplePlanner.ddpg.ddpg import DDPG
from CuriousSamplePlanner.ddpg.naf import NAF
from CuriousSamplePlanner.ddpg.normalized_actions import NormalizedActions
from CuriousSamplePlanner.ddpg.ounoise import OUNoise
from CuriousSamplePlanner.ddpg.param_noise import AdaptiveParamNoiseSpec, ddpg_distance_metric
from CuriousSamplePlanner.ddpg.balanced_replay_memory import BalancedReplayMemory, Transition
from CuriousSamplePlanner.ddpg.replay_memory import ReplayMemory

import sys

def main():
	exp_id = str(sys.argv[1])
	
	experiment_dict = {
		"world_model_losses": [],
		"num_sampled_nodes": 0,
		"exp_id": exp_id,
		"task": "ThreeBlocks",
		'batch_size': 128,
		'actor_lr': 1e-4,
		'critic_lr': 1e-3,
		'eps': 1e-5,
		'num_episodes': 100000,
		'tau': 0.001,
		'gamma': 0.9,
		'ou_noise': True,
		'param_noise': False,
		'noise_scale': 0.3,
		'final_noise_scale': 0.05,
		'exploration_end': 100,
		'seed': 4,
		'updates_per_step': 1,
		'use_gae': False,
		'enable_asm': False,
		'detailed_gmp': False,
		'seed': time.time(),
		'cuda_deterministic': False,
		'num_processes': 1,
		'hidden_size': 64,
		'log_interval': 100,
		'save_interval': 100,
		'eval_interval': None,
		'num_env_steps': 1e7,
		'use_splitter': False, # Can't use splitter on ppo or a2c because they are on-policy algorithms
		'split': 0.5,
		'terminate_unreachable': False,
		'log_dir': '/tmp/gym/',
		'nsamples_per_update': 1024,
		'mode': 'RandomStateEmbeddingPlanner',
		'training': True, 
		'save_dir': './trained_models/',
		'store_true':False,
		'use_proper_time_limits': False,
		'reset_frequency': 0.01,
		'use_linear_lr_decay': False,
		'replay_size': 100000,
		'rewards': []
	}
	rewards = []
	if(torch.cuda.is_available()):
		prefix = "/mnt/fs0/arc11_2/solution_data/"
	else:
		prefix = "./solution_data/"

	experiment_dict['exp_path'] = prefix + experiment_dict["exp_id"]

	if (os.path.isdir(experiment_dict['exp_path'])):
		shutil.rmtree(experiment_dict['exp_path'])
	os.mkdir(experiment_dict['exp_path'])

	torch.manual_seed(experiment_dict['seed'])
	torch.cuda.manual_seed_all(experiment_dict['seed'])

	if torch.cuda.is_available() and experiment_dict["cuda_deterministic"]:
		torch.backends.cudnn.benchmark = False
		torch.backends.cudnn.deterministic = True

	torch.set_num_threads(1)

	PC = getattr(sys.modules[__name__], experiment_dict['task'])
	env = PC(experiment_dict)

	action_low = -1
	action_high = 1
	updates = 0

	agent = DDPG(experiment_dict['gamma'], experiment_dict['tau'], experiment_dict['hidden_size'], env.config_size, env.action_space, actor_lr = experiment_dict['actor_lr'], critic_lr = experiment_dict["critic_lr"])
	agent.cuda()
	if(experiment_dict['use_splitter']):
		memory = BalancedReplayMemory(experiment_dict['replay_size'], split=experiment_dict["split"])
	else:
		memory = ReplayMemory(experiment_dict['replay_size'])

	ounoise = OUNoise(env.action_space.shape[0]) if experiment_dict['ou_noise'] else None
	param_noise = AdaptiveParamNoiseSpec(initial_stddev=0.05, desired_action_stddev=experiment_dict['noise_scale'], adaptation_coefficient=1.05) if experiment_dict['param_noise'] else None
	obs = env.reset()
	total_numsteps = 0
	# Create the replay buffer for training world models
	start = time.time()
	no_reward_frame_count = 0
	MAX_NRFC = 100


	for i_episode in range(experiment_dict['num_episodes']):
		state = env.reset()
		if experiment_dict['ou_noise']: 
			ounoise.scale = (experiment_dict['noise_scale'] - experiment_dict['final_noise_scale']) * max(0, experiment_dict['exploration_end'] - i_episode) / experiment_dict['exploration_end'] + experiment_dict['final_noise_scale']
			ounoise.reset()
		if experiment_dict['param_noise']:
			agent.perturb_actor_parameters(param_noise)

		traj_length = 0
		while True:
			action = agent.select_action(state, ounoise, param_noise)
			next_state, reward, done, infos, inputs, prestate, feasible, command = env.step(action)

			total_numsteps += 1
			action = action
			mask = opt_cuda(torch.Tensor([not done]))
			reward = opt_cuda(torch.Tensor([reward]))
			experiment_dict['rewards'].append(reward.item())

			if(experiment_dict['use_splitter']):
				memory.push(int(reward.item() == 1), state, action, mask, next_state, reward)
			else:
				memory.push(state, action, mask, next_state, reward)

			state = opt_cuda(next_state.type(torch.FloatTensor))
			if len(memory) > experiment_dict['batch_size']:
				for _ in range(experiment_dict['updates_per_step']):
					transitions = memory.sample(experiment_dict['batch_size'])
					batch = Transition(*zip(*transitions))
					value_loss, policy_loss = agent.update_parameters(batch)
					updates += 1


			if total_numsteps % experiment_dict['save_interval'] == 0:
				with open(experiment_dict['exp_path'] + "/exp_dict.pkl", "wb") as fa:
					pickle.dump(experiment_dict, fa)

			if total_numsteps % experiment_dict['log_interval'] == 0:
				print("Episode: "+str(i_episode)+", total numsteps: "+str(total_numsteps)+", average reward: "+str(np.mean(np.array(experiment_dict['rewards'][-100:]))))
		
			if done[0] or traj_length >= 20:
				break

			traj_length+=1
		
		# Update param_noise based on distance metric
		if experiment_dict['param_noise'] and len(memory) >= experiment_dict['batch_size']:
			episode_transitions = memory.memory[memory.position-experiment_dict['batch_size']:memory.position]
			states = torch.cat([transition[0] for transition in episode_transitions], 0)
			unperturbed_actions = agent.select_action(states, None, None)
			perturbed_actions = torch.cat([transition[1] for transition in episode_transitions], 0)

			ddpg_dist = ddpg_distance_metric(perturbed_actions.detach().cpu().numpy(), unperturbed_actions.detach().cpu().numpy())
			param_noise.adapt(ddpg_dist)


if __name__ == "__main__":
	main()
