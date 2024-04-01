#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import json
import os
import time
import sys
from math import cos,sin,pi,sqrt,pow,atan2
from geometry_msgs.msg import Point,PoseWithCovarianceStamped
from nav_msgs.msg import Odometry,Path
from morai_msgs.msg import CtrlCmd,EgoVehicleStatus, GetTrafficLightStatus
import numpy as np
import tf
from tf.transformations import euler_from_quaternion,quaternion_from_euler

from lib.mgeo.class_defs import *

current_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(current_path)

# advanced_purepursuit 은 차량의 차량의 종 횡 방향 제어 예제입니다.
# Purpusuit 알고리즘의 Look Ahead Distance 값을 속도에 비례하여 가변 값으로 만들어 횡 방향 주행 성능을 올립니다.
# 횡방향 제어 입력은 주행할 Local Path (지역경로) 와 차량의 상태 정보 Odometry 를 받아 차량을 제어 합니다.
# 종방향 제어 입력은 목표 속도를 지정 한뒤 목표 속도에 도달하기 위한 Throttle control 을 합니다.
# 종방향 제어 입력은 longlCmdType 1(Throttle control) 이용합니다.

# 노드 실행 순서 
# 0. 필수 학습 지식
# 1. subscriber, publisher 선언
# 2. 속도 비례 Look Ahead Distance 값 설정
# 3. 좌표 변환 행렬 생성
# 4. Steering 각도 계산
# 5. PID 제어 생성
# 6. 도로의 곡률 계산
# 7. 곡률 기반 속도 계획
# 8. 제어입력 메세지 Publish

#TODO: (0) 필수 학습 지식
'''
# advanced_purepursuit 은 Pure Pursuit 알고리즘을 강화 한 예제입니다.
# 이전까지 사용한 Pure Pursuit 알고리즘은 고정된 전방주시거리(Look Forward Distance) 값을 사용하였습니다.
# 해당 예제에서는 전방주시거리(Look Forward Distance) 값을 주행 속도에 비례한 값으로 설정합니다.
# 이때 최소 최대 전방주시거리(Look Forward Distance) 를 설정합니다.
# 주행 속도에 비례한 값으로 변경 한 뒤 "self.lfd_gain" 을 변경 하여서 직접 제어기 성능을 튜닝 해보세요.
# 

'''
class pure_pursuit :
    def __init__(self):
        rospy.init_node('pure_pursuit', anonymous=True)

        #TODO: (1) subscriber, publisher 선언
        '''
        # Local/Gloabl Path 와 Odometry Ego Status 데이터를 수신 할 Subscriber 를 만들고 
        # CtrlCmd 를 시뮬레이터로 전송 할 publisher 변수를 만든다.
        # CtrlCmd 은 1장을 참고 한다.
        # Ego topic 데이터는 차량의 현재 속도를 알기 위해 사용한다.
        # Gloabl Path 데이터는 경로의 곡률을 이용한 속도 계획을 위해 사용한다.
        '''
        # arg = rospy.myargv(argv=sys.argv)
        # local_path_name = arg[1]

        # rospy.Subscriber(local_path_name, Path, self.path_callback)
        rospy.Subscriber("/global_path",Path, self.global_path_callback )
        rospy.Subscriber("/local_path", Path, self.path_callback )
        rospy.Subscriber("/odom", Odometry, self.odom_callback )
        rospy.Subscriber("/Ego_topic", EgoVehicleStatus, self.status_callback)
        rospy.Subscriber('/GetTrafficLightStatus', GetTrafficLightStatus, self.traffic_light_callback)
        self.ctrl_cmd_pub = rospy.Publisher("/ctrl_cmd", CtrlCmd, queue_size=10)

        self.ctrl_cmd_msg = CtrlCmd()
        self.ctrl_cmd_msg.longlCmdType = 1

        self.is_path = False
        self.is_odom = False 
        self.is_status = False
        self.is_global_path = False

        self.is_look_forward_point = False

        self.forward_point = Point()
        self.current_postion = Point()

        self.vehicle_length = 2.6
        self.lfd = 8
        self.min_lfd = 5
        self.max_lfd = 30
        self.lfd_gain = 0.78
        self.target_velocity = 30
        self.traffic_light_status = 16
        self.traffic_light_idx = ''

        self.pid = pidControl()
        self.vel_planning = velocityPlanning(self.target_velocity/3.6, 0.15)

        load_path = os.path.normpath(os.path.join(current_path, 'lib/mgeo_data/R_KR_PG_K-City'))
        mgeo_planner_map = MGeo.create_instance_from_json(load_path)

        traffic_light_set = mgeo_planner_map.light_set
        self.trafficlights = traffic_light_set.signals

        self.bus_stop = False
        self.bus_idx = 0

        self.now_time = 0.0
        self.prev_time = 0.0
        

        self.bus_stop_path = dict()
        with open(os.path.join(current_path, 'lib/mgeo_data/bus_stop.json')) as f:
            self.bus_stop_path = json.load(f)

        # rospy.loginfo(self.bus_stop[0]["point"])

        while True:
            if self.is_global_path == True:
                self.velocity_list = self.vel_planning.curvedBaseVelocity(self.global_path, 50)
                break
            else:
                rospy.loginfo('Waiting global path data')

        rate = rospy.Rate(30) # 30hz
        while not rospy.is_shutdown():
            if self.is_path == True and self.is_odom == True and self.is_status == True:
                self.now_time = time.time()
                if self.bus_stop:
                    if self.now_time-self.prev_time>6.0:
                        self.bus_stop = False
                        self.prev_time = self.now_time
                else:
                    self.current_waypoint = self.get_current_waypoint(self.status_msg,self.global_path)
                    self.target_velocity = self.velocity_list[self.current_waypoint]*3.6

                    steering = self.calc_pure_pursuit()
                    if self.is_look_forward_point :
                        self.ctrl_cmd_msg.steering = steering
                    else : 
                        rospy.loginfo("no found forward point")
                        self.ctrl_cmd_msg.steering = 0.0
                    
                    output = self.pid.pid(self.target_velocity,self.status_msg.velocity.x*3.6)

                    if output > 0.0:
                        self.ctrl_cmd_msg.accel = output
                        self.ctrl_cmd_msg.brake = 0.0
                    else:
                        self.ctrl_cmd_msg.accel = 0.0
                        self.ctrl_cmd_msg.brake = -output

                    light_stop = False
                    ego_x = self.status_msg.position.x
                    ego_y = self.status_msg.position.y
                    ego_z = self.status_msg.position.z
                    for idx, signal in self.trafficlights.items():
                        if idx == self.traffic_light_idx:
                            trafficlight_x = signal.point[0]
                            trafficlight_y = signal.point[1]
                            trafficlight_z = signal.point[2]
                            
                            dist_light = sqrt(pow(ego_x-trafficlight_x,2)+pow(ego_y-trafficlight_y,2)+pow(ego_z-trafficlight_z,2))
                            if dist_light<=20.0:
                                light_stop = True

                    if light_stop:
                        if self.traffic_light_status == 4 or self.traffic_light_status == 1:
                            self.ctrl_cmd_msg.accel = 0.0
                            self.ctrl_cmd_msg.brake = 1.0

                    for bus in self.bus_stop_path:
                        if self.bus_idx==bus["idx"]:
                            continue
                        point = bus["point"]
                        dist_bus = sqrt(pow(ego_x-point[0], 2)+pow(ego_y-point[1], 2)+pow(ego_z-point[2],2))
                        if dist_bus <= 3.5:
                            self.bus_stop = True
                            self.bus_idx = bus["idx"]
                            break

                    if self.bus_stop:
                        self.ctrl_cmd_msg.accel = 0.0
                        self.ctrl_cmd_msg.brake = 1.0
                        self.prev_time = self.now_time

                    #TODO: (8) 제어입력 메세지 Publish
                    self.ctrl_cmd_pub.publish(self.ctrl_cmd_msg)
                
            rate.sleep()

    def path_callback(self,msg):
        self.is_path=True
        self.path=msg  

    def odom_callback(self,msg):
        self.is_odom=True
        odom_quaternion=(msg.pose.pose.orientation.x,msg.pose.pose.orientation.y,msg.pose.pose.orientation.z,msg.pose.pose.orientation.w)
        _,_,self.vehicle_yaw=euler_from_quaternion(odom_quaternion)
        self.current_postion.x=msg.pose.pose.position.x
        self.current_postion.y=msg.pose.pose.position.y

    def status_callback(self,msg): ## Vehicl Status Subscriber 
        self.is_status=True
        self.status_msg=msg  
        
    def global_path_callback(self,msg):
        self.global_path = msg
        self.is_global_path = True

    def traffic_light_callback(self, msg):
        self.traffic_light_status = msg.trafficLightStatus
        self.traffic_light_idx = msg.trafficLightIndex
    
    def get_current_waypoint(self,ego_status,global_path):
        min_dist = float('inf')        
        currnet_waypoint = -1
        for i,pose in enumerate(global_path.poses):
            dx = ego_status.position.x - pose.pose.position.x
            dy = ego_status.position.y - pose.pose.position.y

            dist = sqrt(pow(dx,2)+pow(dy,2))
            if min_dist > dist :
                min_dist = dist
                currnet_waypoint = i
        return currnet_waypoint

    def calc_pure_pursuit(self,):

        #TODO: (2) 속도 비례 Look Ahead Distance 값 설정
        '''
        # 차량 속도에 비례하여 전방주시거리(Look Forward Distance) 가 변하는 수식을 구현 합니다.
        # 이때 'self.lfd' 값은 최소와 최대 값을 넘어서는 안됩니다.
        # "self.min_lfd","self.max_lfd", "self.lfd_gain" 을 미리 정의합니다.
        # 최소 최대 전방주시거리(Look Forward Distance) 값과 속도에 비례한 lfd_gain 값을 직접 변경해 볼 수 있습니다.
        # 초기 정의한 변수 들의 값을 변경하며 속도에 비례해서 전방주시거리 가 변하는 advanced_purepursuit 예제를 완성하세요.
        '''
        self.lfd = max(self.min_lfd, min(self.lfd_gain * self.status_msg.velocity.x, self.max_lfd))

        vehicle_position=self.current_postion
        self.is_look_forward_point= False

        translation = [vehicle_position.x, vehicle_position.y]

        #TODO: (3) 좌표 변환 행렬 생성
        '''
        # Pure Pursuit 알고리즘을 실행 하기 위해서 차량 기준의 좌표계가 필요합니다.
        # Path 데이터를 현재 차량 기준 좌표계로 좌표 변환이 필요합니다.
        # 좌표 변환을 위한 좌표 변환 행렬을 작성합니다.
        # Path 데이터를 차량 기준 좌표 계로 변환 후 Pure Pursuit 알고리즘 중 전방주시거리(Look Forward Distance) 와 가장 가까운 Path Point 를 찾습니다.
        # 전방주시거리(Look Forward Distance) 와 가장 가까운 Path Point 를 이용하여 조향 각도를 계산하게 됩니다.
        # 좌표 변환 행렬을 이용해 Path 데이터를 차량 기준 좌표 계로 바꾸는 반복 문을 작성 한 뒤
        # 전방주시거리(Look Forward Distance) 와 가장 가까운 Path Point 를 계산하는 로직을 작성 하세요.

        '''
        trans_matrix = np.array([   [cos(self.vehicle_yaw), -sin(self.vehicle_yaw),translation[0]],
                                    [sin(self.vehicle_yaw), cos(self.vehicle_yaw), translation[1]],
                                    [0,0,1]])

        det_trans_matrix = np.linalg.inv(trans_matrix)   # np.linalg.inv : 역행렬

        for pose in self.path.poses:
            path_point = pose.pose.position

            global_path_point = [path_point.x, path_point.y, 1]
            local_path_point = det_trans_matrix.dot(global_path_point)   # 단위행렬

            if local_path_point[0]>0 :
                dis = sqrt(pow(local_path_point[0],2)+ pow(local_path_point[1],2))  # local_path_point.distance()
                if dis >= self.lfd :
                    self.forward_point = path_point
                    self.is_look_forward_point = True
                    break

        #TODO: (4) Steering 각도 계산
        '''
        # 제어 입력을 위한 Steering 각도를 계산 합니다.
        # theta 는 전방주시거리(Look Forward Distance) 와 가장 가까운 Path Point 좌표의 각도를 계산 합니다.
        # Steering 각도는 Pure Pursuit 알고리즘의 각도 계산 수식을 적용하여 조향 각도를 계산합니다.

        '''
        theta = atan2(self.forward_point.y - vehicle_position.y, self.forward_point.x - vehicle_position.x)
        alpha = theta - self.vehicle_yaw
        L = sqrt(pow(self.forward_point.y - vehicle_position.y, 2) + pow(self.forward_point.x - vehicle_position.x, 2))
        steering = atan2(2.0 * self.vehicle_length * sin(alpha) / L, 1.0)

        return steering

class pidControl:
    def __init__(self):
        self.p_gain = 0.3
        self.i_gain = 0.00
        self.d_gain = 0.03
        self.prev_error = 0
        self.i_control = 0
        self.controlTime = 0.02

    def pid(self,target_vel, current_vel):
        error = target_vel - current_vel

        #TODO: (5) PID 제어 생성
        '''
        # 종방향 제어를 위한 PID 제어기는 현재 속도와 목표 속도 간 차이를 측정하여 Accel/Brake 값을 결정 합니다.
        # 각 PID 제어를 위한 Gain 값은 "class pidContorl" 에 정의 되어 있습니다.
        # 각 PID Gain 값을 직접 튜닝하고 아래 수식을 채워 넣어 P I D 제어기를 완성하세요.

        '''
        # PID 제어 생성
        p_control = self.p_gain * error
        self.i_control += self.i_gain * error * self.controlTime
        d_control = self.d_gain * (error - self.prev_error) / self.controlTime

        # output : accel 값
        output = p_control + self.i_control + d_control
        self.prev_error = error

        return output

class velocityPlanning:
    def __init__ (self,car_max_speed, road_friciton):
        self.car_max_speed = car_max_speed
        self.road_friction = road_friciton

    def curvedBaseVelocity(self, gloabl_path, point_num):
        out_vel_plan = []

        for i in range(0,point_num):
            out_vel_plan.append(self.car_max_speed)

        for i in range(point_num, len(gloabl_path.poses) - point_num):
            x_list = []
            y_list = []
            for box in range(-point_num, point_num):
                x = gloabl_path.poses[i+box].pose.position.x
                y = gloabl_path.poses[i+box].pose.position.y
                x_list.append([-2*x, -2*y ,1])
                y_list.append((-x*x) - (y*y))

            #TODO: (6) 도로의 곡률 계산
            '''
            # 도로의 곡률 반경을 계산하기 위한 수식입니다.
            # Path 데이터의 좌표를 이용해서 곡선의 곡률을 구하기 위한 수식을 작성합니다.
            # 원의 좌표를 구하는 행렬 계산식, 최소 자승법을 이용하는 방식 등 곡률 반지름을 구하기 위한 식을 적용 합니다.
            # 적용한 수식을 통해 곡률 반지름 "r" 을 계산합니다.

            '''
            x_array = np.array(x_list)
            y_array = np.array(y_list)
            sol = np.linalg.lstsq(x_array, y_array, rcond=None)
            a, b = sol[0][0], sol[0][1]
            c = pow(a,2)+pow(b,2)
            r = sqrt(c-sol[0][2])

            #TODO: (7) 곡률 기반 속도 계획
            '''
            # 계산 한 곡률 반경을 이용하여 최고 속도를 계산합니다.
            # 평평한 도로인 경우 최대 속도를 계산합니다. 
            # 곡률 반경 x 중력가속도 x 도로의 마찰 계수 계산 값의 제곱근이 됩니다.
            '''
            g_accel = 9.8
            friction = 0.7
            v_max = sqrt(r*g_accel*friction)

            if v_max > self.car_max_speed:
                v_max = self.car_max_speed
            out_vel_plan.append(v_max)

        for i in range(len(gloabl_path.poses) - point_num, len(gloabl_path.poses)-10):
            out_vel_plan.append(30)

        for i in range(len(gloabl_path.poses) - 10, len(gloabl_path.poses)):
            out_vel_plan.append(0)

        return out_vel_plan

if __name__ == '__main__':
    try:
        test_track=pure_pursuit()
    except rospy.ROSInterruptException:
        pass
