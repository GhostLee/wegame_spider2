# encoding:utf-8

import requests
import json
import time
import math
import os
import pickle
from tqdm import tqdm
from urllib import parse
from config import LOL_GameArea

import urllib3
urllib3.disable_warnings()  # 消除SSL认证警告


class Player:
    def __init__(self, nickname, id, area):
       self.nickname = nickname
       self.id = id
       self.area = area


class Battle:
    bat_id = None  # 对局id
    bat_mode = None  # 对局模式
    bat_use_hero = None  # 使用英雄
    bat_kill = None  # 击杀数
    bat_death = None  # 死亡数
    bat_assist = None  # 助攻数
    bat_desc = None  # 对局备注
    bat_time = None  # 对局时间
    bat_score = None  # 对局评分
    is_win = None  # 胜负


class Spider_WeGame:
    def __init__(self, login_data, headers,infos_dir=None):
        # 建立一个会话
        self.login_data=login_data
        self.infos_dir=infos_dir
        self.session = requests.Session()
        # 设置请求头
        self.session.headers = headers
        # 这个与config中的qqinfo_ext->sig要一致
        self.session.cookies['skey'] = login_data["login_info"]["sig"]
        self.login()

    def login(self):
        # 登录请求url
        login_url = 'https://www.wegame.com.cn/api/middle/clientapi/auth/login_by_qq'
        # 请求登录
        info=self.session.post(login_url, data=json.dumps(self.login_data), verify=False)
        # 判断登录是否成功
        if self.session.cookies.get('tgp_ticket', None):
            # self.session.headers.pop('Referer')  # 登录时需要用到,登录成功后就不需要了
            print('spider landing success')
            return True
        else:
            print('spider landing fail')
            return False

    def search_lol_user(self, nickname, area=None):
        search_url = 'https://m.wegame.com.cn/api/mobile/lua/proxy/index/mwg_lol_proxy/query_by_nick'
        # post请求需要的json数据
        data = {
            'search_nick': nickname
        }
        resp = self.session.post(search_url, data=json.dumps(data), verify=False).json()['data']['player_list']

        # 判断是否输入了大区
        area_key = None
        # 通过大区名找到大区id
        if area:
            foo = [k for k, v in LOL_GameArea.items() if v['name'] == area]
            try:
                area_key = int(foo[0])
            except IndexError:
                print('未找到对应大区..请查看是否输入有误')

        player_list = []
        for foo in resp:
            # 如果输入了大区,则只找对应大区的召唤师
            if area_key:
                if area_key != foo['area_id']:
                    continue

            player = Player()
            player.lol_id = foo['slol_id']  # 游戏id
            player.lol_nick = foo['game_nick']  # 游戏昵称
            player.lol_area = foo["area_id"]  # 游戏大区
            player.lol_rank = foo['rank_title']  # rank
            player.lol_head = foo['icon_url']  # 游戏头像
            player_list.append(player)

        return player_list

    def get_battle_detail(self, player, game_id, delay=0):
        url = 'https://www.wegame.com.cn/api/v1/wegame.pallas.game.LolBattle/GetBattleDetail'

        data = {"account_type":3,
                "id": player.id,
                "area":player.area,
                "game_id":int(game_id),
                "from_src":"lol_helper"}
        time.sleep(delay)
        resp = self.session.post(url, data=json.dumps(data), verify=False).json()

        return resp

    def get_player_battle_infos(self, player: Player, filter_type="", limit=1, quite=False):
        all_results = []
        tmp_pkl_name=self.infos_dir+"/"+f"battle_overview_{player.nickname}_area{player.area}_limit{limit}_filter{filter_type}.pkl"

        if os.path.exists(tmp_pkl_name) and limit>1:
            with open(tmp_pkl_name,"rb") as fid:
                all_resp = pickle.load(fid)
        else:
            all_resp = []
            url = 'https://www.wegame.com.cn/api/v1/wegame.pallas.game.LolBattle/GetBattleList'
            lop_length=10
            max_loop_cnt= math.ceil(limit/lop_length)
            for loop_i in tqdm(range(max_loop_cnt),desc="FetchData",disable=quite):
                start_idx = loop_i*lop_length
                length = min((loop_i+1)*lop_length,limit)-start_idx
                data={"account_type":3,
                      "id":player.id,
                      "area":player.area,
                      "offset":start_idx,
                      "count":length,
                      "filter":filter_type,
                      "from_src":"lol_helper"}
                resp = self.session.post(url, data=json.dumps(data), verify=False).json()['battles']
                time.sleep(3)
                all_resp.extend(resp)

            if limit>1:
                with open(tmp_pkl_name, "wb") as fid:
                    pickle.dump(all_resp,fid)

        for info in tqdm(all_resp, desc="GetBattleDetail",disable=quite):
            all_details = self.get_battle_detail(player, info["game_id"], delay=2)
            if all_details["result"]["error_message"] != 'success':
                raise RuntimeError(f"can't load {info}")

            battle_detail = all_details['battle_detail']
            time_cost = battle_detail['game_time_played']
            red_blue_players= {"Win":[],"Fail":[]}
            for road_player in battle_detail['player_details']:
                state = "Win" if "Win" in road_player["win"] else "Fail"
                red_blue_players[state].append(parse.unquote(road_player["name"]))

            if player.nickname in red_blue_players["Win"]:
                friend = red_blue_players["Win"]
                enemy = red_blue_players["Fail"]
            else:
                friend = red_blue_players["Fail"]
                enemy = red_blue_players["Win"]
            start_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(info['game_start_time']) / 1000.))

            battle_data={
                "game_id": info["game_id"],
                "timestamp": info['game_start_time'],
                "timestamp_h": start_time,
                "time_cost": time_cost,
                'game_mode': battle_detail['game_mode'],
                'game_type': battle_detail['game_type'],
                'friend_player': friend,
                'enemy_player': enemy,
            }
            all_results.append(battle_data)

        return all_results

    def generate_record(self, player_target, limit=500, saving_name=""):
        myName= "籍籍无名哈撒给"
        # player = self.search_lol_user(myName)[0]
        # print(f'玩家id:{player.lol_id}|玩家昵称:{player.lol_nick}|所在大区:{LOL_GameArea[str(player.lol_area)]["name"]} |段位:{player.lol_rank}')

        infos=self.get_player_battle_infos(player_target, limit=limit)
        infos_name = self.infos_dir+"/"+ saving_name
        with open(infos_name,"wb") as fid:
            pickle.dump(infos,fid)

    def big_bro_watching_u(self, player_puppy, dove, mode=0):
        if mode == 0:
            check_latency= 4*60  # second 5*60
            report_latency= 8*3600 # min 24*3600
            running_checkpoint=time.time()
            latest_info=None

            while True:
                timestamp=time.time()
                now_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
                interval = float(timestamp-running_checkpoint)/60
                if interval>report_latency:
                    running_checkpoint = timestamp
                    error_flag=dove.send(f"{now_time}", "NoticeOn")
                    if error_flag:
                        raise RuntimeError(f"{now_time} dove down")

                try:
                    infos = self.get_player_battle_infos(player_puppy, limit=1, quite=True)
                    if len(infos) == 0:
                        raise
                except:
                    message=f"{now_time} spider down!"
                    error_flag=dove.send(message, "NoticeDown")
                    if error_flag:
                        raise RuntimeError(f"{now_time} Spider&Dove BOOM BOOM BOOM")
                    raise RuntimeError(f"{now_time} {message}")

                if latest_info is None or infos[0]["timestamp_h"] != latest_info["timestamp_h"]:
                    latest_info=infos[0]
                    friend=latest_info['friend_player']
                    game_mode=latest_info['game_mode']
                    ngame_time=latest_info['timestamp_h']
                    message=f"{ngame_time} {game_mode}:{int(latest_info['time_cost']/60)}min {friend}"
                    message=message.replace("\'","").replace(player_puppy.nickname+", ", "")
                    print(f"{now_time} {message}")
                    error_flag=dove.send(message,"NoticeHit")
                    if error_flag:
                        raise RuntimeError(f"{now_time} dove down")

                time.sleep(check_latency)

class Analysis():
    def __init__(self, record_dir):
        with open(record_dir,"rb") as fid:
            self.record = pickle.load(fid)

    def friend_analysis(self):
        friend_infos={}
        enemy_infos={}
        game_modes=set([])
        for infos in tqdm(self.record):
            game_modes.add(infos["game_mode"])
            friends=infos["friend_player"]
            enemies=infos["enemy_player"]
            for idx in range(5):
                if friends[idx] in friend_infos.keys():
                    friend_infos[friends[idx]][0]+=1
                    friend_infos[friends[idx]][1].append(infos["timestamp_h"])
                else:
                    friend_infos[friends[idx]] = [1, [infos["timestamp_h"]],infos["timestamp"]]

                if enemies[idx] in enemy_infos.keys():
                    enemy_infos[enemies[idx]][0] += 1
                    enemy_infos[enemies[idx]][1].append(infos["timestamp_h"])
                else:
                    enemy_infos[enemies[idx]] = [1, [infos["timestamp_h"]],infos["timestamp"]]

        friend_infos_sorted=sorted(friend_infos.items(), key=lambda kv: (-kv[1][0],-int(kv[1][2])))
        enemy_infos_sorted=sorted(enemy_infos.items(), key=lambda kv: (-kv[1][0],-int(kv[1][2])))

        friend_also_enemy=[]
        enemy_names = [item[0] for item in enemy_infos_sorted]
        for friend in friend_infos_sorted:
            friend_name=friend[0]
            if friend_name in enemy_names:
                friend_also_enemy.append({friend_name:friend})

        # friend_also_enemy=set([item[0] for item in friend_infos_sorted])&set([item[0] for item in enemy_infos_sorted])
        print("Done friend play analysis")

    def date_timestamp_analysis(self, recent=None):
        date_cnt={}
        time_cnt={}
        weekly_cnt={}

        datas=self.record if recent is None else self.record[:recent]
        for infos in tqdm(datas):
            date=infos["timestamp_h"].split(" ")[0]
            hour=infos["timestamp_h"].split(" ")[1].split(":")[0]
            weekly_name = time.strftime("%A", time.localtime(float(infos["timestamp"]) / 1000.))

            if date in date_cnt.keys():
                date_cnt[date]+=1
            else:
                date_cnt[date]=1

            if hour in time_cnt.keys():
                time_cnt[hour]+=1
            else:
                time_cnt[hour]=1

            if weekly_name in weekly_cnt.keys():
                weekly_cnt[weekly_name]+=1
            else:
                weekly_cnt[weekly_name]=1

        date_cnt_sorted=sorted(date_cnt.items(), key=lambda kv: (kv[0]))
        time_cnt_sorted=sorted(time_cnt.items(), key=lambda kv: (kv[0]))
        weekly_cnt=weekly_cnt
        print("Done timestamp play analysis")

    def pickup_date_all_battles(self, date_target=("2021-10-28",)):
        results=[]
        for infos in tqdm(self.record):
            date=infos["timestamp_h"].split(" ")[0]
            if date in date_target:
                results.append(infos)
        print(f"Done target_date analysis")

    def game_analysis(self):
        games_type=set([])
        games_mode=set([])
        games_mode_cnt={}
        for infos in tqdm(self.record):
            games_type.add(infos["game_type"])
            games_mode.add(infos["game_mode"])
            if infos["game_mode"] in games_mode_cnt.keys():
                games_mode_cnt[infos["game_mode"]]+=1
            else:
                games_mode_cnt[infos["game_mode"]]=1
        print(f"Games_type{games_type}, Game types: {games_mode_cnt}")


if __name__ == '__main__':
    from config import  HEADERS as headers
    from config import LOGIN_DATA as login_data
    data_dir="battle_infos"
    os.makedirs(data_dir,exist_ok=True)
    spider = Spider_WeGame(login_data, headers, data_dir)

    ids=[
        # {"id":"L17813315232880175925","area":16,"nickname":"DevinVesper"},
        # {"id":"L18160673698990541216","area": 1,"nickname":"DevinVesper"},
        # {"id":"L16613047346631875848","area": 1,"nickname":"VesperDevin"},
        {"id":"L13500438156688788059","area": 1,"nickname":"籍籍无名哈撒给"},
    ]

    #  # watcher ----------------------------------------------------------------------------
    from watcher import Email163 as dove
    puppy = {"id": "L16613047346631875848", "area": 1, "nickname":"VesperDevin"}
    player_puppy = Player(puppy['nickname'], puppy['id'], puppy['area'])
    spider.big_bro_watching_u(player_puppy,dove(), mode=0)
    raise RuntimeError
    #  # analysis ----------------------------------------------------------------------------
    limit=500
    for item in ids:
        player = Player(item['nickname'], item['id'], item['area'])
        saving_name = f"{player.nickname}_area{player.area}_{limit}.pkl"
        # spider.generate_record(player, limit, saving_name)

        print(f"Analysis item:{item}","*"*40)
        recorder_path=data_dir+"/"+saving_name
        ana_recorder = Analysis(recorder_path)
        ana_recorder.pickup_date_all_battles()
        ana_recorder.game_analysis()
        ana_recorder.friend_analysis()
        ana_recorder.date_timestamp_analysis()
