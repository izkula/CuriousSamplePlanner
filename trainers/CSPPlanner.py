#!/usr/bin/env python
from __future__ import print_function
import pybullet as p
import numpy as np
import time
import random
import math
import imageio
import matplotlib.pyplot as plt
import os
import shutil
import h5py
import imageio
from CuriousSamplePlanner.planning_pybullet.pybullet_tools.kuka_primitives import BodyPose, BodyConf, Command, get_grasp_gen, \
	get_ik_fn, get_free_motion_gen, get_holding_motion_gen
from CuriousSamplePlanner.planning_pybullet.pybullet_tools.utils import WorldSaver, enable_gravity, connect, dump_world, set_pose, \
	Pose, Point, Euler, set_default_camera, stable_z, \
	BLOCK_URDF, load_model, wait_for_user, disconnect, DRAKE_IIWA_URDF, user_input, update_state, disable_real_time,inverse_kinematics,end_effector_from_body,approach_from_grasp, get_joints, get_joint_positions


from CuriousSamplePlanner.planning_pybullet.pybullet_tools.utils import get_pose, set_pose, get_movable_joints, \
	set_joint_positions, add_fixed_constraint, enable_real_time, disable_real_time, joint_controller, \
	enable_gravity, get_refine_fn, user_input, wait_for_duration, link_from_name, get_body_name, sample_placement, \
	end_effector_from_body, approach_from_grasp, plan_joint_motion, GraspInfo, Pose, INF, Point, \
	inverse_kinematics, pairwise_collision, remove_fixed_constraint, Attachment, get_sample_fn, \
	step_simulation, refine_path, plan_direct_joint_motion, get_joint_positions, dump_world, get_link_pose,control_joints

from CuriousSamplePlanner.planning_pybullet.pybullet_tools.kuka_primitives import BodyPath, Attach, Detach
import pickle
import torch
from torch import nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import collections
from motion_planners.discrete import astar
import sys
from CuriousSamplePlanner.tasks.three_block_stack import TwoBlocks

from CuriousSamplePlanner.tasks.three_block_stack import ThreeBlocks
from CuriousSamplePlanner.tasks.ball_ramp import BallRamp
from CuriousSamplePlanner.tasks.pulley import PulleySeesaw
from CuriousSamplePlanner.tasks.bookshelf import BookShelf
from CuriousSamplePlanner.tasks.five_block_stack import FiveBlocks

from CuriousSamplePlanner.scripts.utils import *

from CuriousSamplePlanner.trainers.plan_graph import PlanGraph
from CuriousSamplePlanner.trainers.dataset import ExperienceReplayBuffer


from CuriousSamplePlanner.policies.fixed import FixedPolicy
from CuriousSamplePlanner.policies.random import RandomPolicy
from CuriousSamplePlanner.policies.learning import LearningPolicy

class CSPPlanner():
	def __init__(self, experiment_dict):
		self.experiment_dict = experiment_dict

		# Create the replay buffer for training world models
		self.experience_replay = ExperienceReplayBuffer()

		# Create the environment
		EC = getattr(sys.modules[__name__], self.experiment_dict["task"])
		self.environment = EC(experiment_dict)

		# Create the policy
		PC = getattr(sys.modules[__name__], self.experiment_dict["policy"])
		self.policy = PC(experiment_dict, self.environment)

		# Init the plan graph 
		self.graph = PlanGraph(environment=self.environment, node_sampling = self.experiment_dict['node_sampling'])
		super(CSPPlanner, self).__init__()

	def print_exp_dict(self, verbose=False):
		mean_reward = sum(self.experiment_dict['rewards'][-128:])/len(self.experiment_dict['rewards'][-128:])
		print("Sampled: "+str(self.experiment_dict['num_sampled_nodes'])+"\t Graph Size: "+str(self.experiment_dict['num_graph_nodes'])+"\t WM Loss: "+str(self.experiment_dict['world_model_losses'][-1])+"\t Feasibility: "+str(self.experiment_dict['feasibility'][-1])+"\t Reward: "+str(mean_reward))
		# print("Sampled: "+str(self.experiment_dict['num_sampled_nodes'])+"\t Graph Size: "+str(self.experiment_dict['num_graph_nodes'])+"\t WM Loss: "+str(self.experiment_dict['world_model_losses'][-1]))
	
	def save_params(self):
		# Save the updated models
		# with open(self.exp_path + "/worldModel.pkl", 'wb') as fw:
		# 	pickle.dump(self.worldModel, fw)
		# with open(self.exp_path + "/actor_critic.pkl", "wb") as fa:
		# 	pickle.dump(self.environment.actor_critic, fa)
		
		with open(self.experiment_dict['exp_path'] + "/exp_dict.pkl", "wb") as fa:
			pickle.dump(self.experiment_dict, fa)
			fa.close()

		graph_filehandler = open(self.experiment_dict['exp_path'] + "/found_graph.pkl", 'wb')
		pickle.dump(self.graph, graph_filehandler)

	def plan(self):

		# Set up fthe starting position
		self.policy.reset()
		run_index = 0
		start_state = torch.tensor(self.environment.get_start_state())
		start_node = self.graph.add_node(start_state, None, None, None, run_index=run_index)
		total_numsteps = 0
		feature = torch.zeros((1, 3, 84, 84))
		i_episode = 0
		# Begin looping
		while (True):

			total_numsteps += 1
			# Parent State selection from the graph
			parent = self.graph.expand_node(1)[0]
			# Set the environment correctly
			self.environment.set_state(parent.config)
			# Extract the state from the parent node
			parent_state = torch.unsqueeze(opt_cuda(torch.tensor(parent.config)), dim=0)
			# Select the action depending on the policy
			action = self.policy.select_action(parent_state)
			# Take a step in the environment
			next_state, reward, done, infos = self.policy.step(torch.squeeze(action))
			self.experiment_dict["num_sampled_nodes"] += 1
			# print(infos)
			inputs, prestate, feasible, command = infos['inputs'], infos['prestable'], infos['feasible'], infos['command']
			self.experiment_dict['rewards'].append(reward)

			# Store the results
			self.policy.store_results(next_state, reward, done, infos, parent, action)

			if (reward > 0): # Positive reward means success
				self.policy.i_episode  += 1

				# Add the goal node to the graph
				ntarget = torch.squeeze(next_state).cpu().numpy()
				max_z_pos = max([ntarget[2], ntarget[8], ntarget[14]])
				npretarget = prestate.cpu().numpy()
				naction = action.cpu().numpy()
				goal_node = self.graph.add_node(ntarget, npretarget, naction, parent.node_key, command = command, run_index=run_index)
				max_z_pos = max([goal_node.config[2], goal_node.config[8], goal_node.config[14]])
				# Reset the number of graph nodes
				self.experiment_dict["num_graph_nodes"] = 0

				# Exit the planning loop if needed
				if(self.experiment_dict['return_on_solution']):
					return self.graph, self.graph.get_optimal_plan(start_node, goal_node), self.experiment_dict
				else:
					# Found a reward, creating a new graph with a new start node
					self.graph = PlanGraph(environment=self.environment, node_sampling = self.experiment_dict['node_sampling'])
					ss = self.policy.reset().cpu().numpy()[0]
					start_node = self.graph.add_node(ss, None, None, None, run_index=run_index)
					self.reset_world_model()
					self.policy.got_reward()
		

			# Update the policy
			self.policy.update(total_numsteps)

			target = next_state.type(torch.FloatTensor)
			pretarget = prestate.type(torch.FloatTensor)
			action = action.type(torch.FloatTensor)
			parent_nodes = parent.node_key
			feasible = feasible
			combined_perspective = feature.type(torch.FloatTensor)

			self.experience_replay.bufferadd_single(combined_perspective, target, pretarget, action, feasible, parent_nodes, command)

			if(total_numsteps%self.experiment_dict["batch_size"]== 0):
				self.environment.dt = 0.001
				self.train_world_model(0)
				
				# Get the losses from all observations
				whole_losses, whole_indices, whole_feasibles = self.calc_novelty()
				sort_args = np.array(whole_losses).argsort()[::-1]
				high_loss_indices = [whole_indices[p] for p in sort_args]
				average_loss = sum(whole_losses) / len(whole_losses)

				# Update stats
				self.experiment_dict['feasibility'].append((sum(whole_feasibles)/len(whole_feasibles)))
				self.experiment_dict['world_model_losses'].append(average_loss)
				self.print_exp_dict(verbose=False)

				# Adaptive batch
				if (average_loss <= self.experiment_dict["loss_threshold"] or not self.experiment_dict['adaptive_batch']):
					run_index+=1
					added_base_count = 0
					for en_index, hl_index in enumerate(high_loss_indices):
						input, target, pretarget, action, _, parent_index, _ = self.experience_replay.__getitem__(hl_index)
						command = self.experience_replay.get_command(hl_index)
						ntarget = torch.squeeze(target).numpy()
						npretarget = pretarget.cpu().numpy()
						self.environment.set_state(ntarget)
						# for perspective in self.environment.perspectives:
						# 	picture, _, _ = take_picture(perspective[0], perspective[1], 0, size=512)
						# 	imageio.imwrite(self.experiment_dict['exp_path']
						# 					+ '/run_index=' + str(run_index)
						# 					+ ',index=' + str(en_index)
						# 					+ ',parent_index=' + str(int(parent_index))
						# 					+ ',node_index=' + str(self.graph.node_key) + '.jpg',
						# 					picture)


						self.graph.add_node(ntarget, npretarget, action.numpy(), parent_index, command = command, run_index = run_index)
						added_base_count += 1
						if (added_base_count == self.experiment_dict["growth_factor"]):
							break

					del self.experience_replay
					self.experience_replay = ExperienceReplayBuffer()
					self.experiment_dict["num_graph_nodes"] += self.experiment_dict["growth_factor"]

					# Update novelty scores for tree nodes
					self.update_novelty_scores()

				# Save Params
				self.save_params()



			if(self.experiment_dict["num_sampled_nodes"] > self.experiment_dict['sample_cap']):
				return None, None, self.experiment_dict

		return self.graph, plan, self.experiment_dict



