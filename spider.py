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
    nickname = None
    id = None
    lol_id = None  # lol id
    lol_nick = None  # lol昵称
    lol_area = None  # 所在大区
    lol_head = None  # 游戏头像
    lol_rank = None  # rank


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

    def login(self):
        # 登录请求url
        login_url = 'https://www.wegame.com.cn/api/middle/clientapi/auth/login_by_qq'
        # 请求登录
        self.session.post(login_url, data=json.dumps(self.login_data), verify=False)
        # 判断登录是否成功
        if self.session.cookies.get('tgp_ticket', None):
            # self.session.headers.pop('Referer')  # 登录时需要用到,登录成功后就不需要了
            print('登录成功')
            #print(self.session.cookies)
            return True
        else:
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
                "area":player.lol_area,
                "game_id":int(game_id),
                "from_src":"lol_helper"}
        time.sleep(delay)
        resp = self.session.post(url, data=json.dumps(data), verify=False).json()

        return resp

    def get_player_battle_infos(self, player: Player, filter_type="", limit=1):
        all_results = []
        tmp_pkl_name=self.infos_dir+"/"+f"id{player.id}_area{player.lol_area}_limit{limit}_filter{filter_type}.pkl"

        if os.path.exists(tmp_pkl_name):
            with open(tmp_pkl_name,"rb") as fid:
                all_resp = pickle.load(fid)
        else:
            all_resp = []
            url = 'https://www.wegame.com.cn/api/v1/wegame.pallas.game.LolBattle/GetBattleList'
            lop_length=10
            max_loop_cnt= math.ceil(limit/lop_length)
            for loop_i in tqdm(range(max_loop_cnt),desc="FetchData"):
                start_idx = loop_i*lop_length
                length = min((loop_i+1)*lop_length,limit)-start_idx

                data={"account_type":3,
                      "id":player.id,
                      "area":player.lol_area,
                      "offset":start_idx,
                      "count":length,
                      "filter":filter_type,
                      "from_src":"lol_helper"}

                resp = self.session.post(url, data=json.dumps(data), verify=False).json()['battles']
                time.sleep(3)
                all_resp.extend(resp)
            with open(tmp_pkl_name, "wb") as fid:
                pickle.dump(all_resp,fid)

        for info in tqdm(all_resp, desc="GetBattleDetail"):
            all_details = self.get_battle_detail(player, info["game_id"], delay=1.5)
            if all_details["result"]["error_message"] != 'success':
                raise RuntimeError(f"can't load {info}")

            battle_detail = all_details['battle_detail']
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
                'game_mode': battle_detail['game_mode'],
                'game_type': battle_detail['game_type'],
                'friend_player': friend,
                'enemy_player': enemy,
            }
            all_results.append(battle_data)

        return all_results

    def generate_record(self, nickname, id, limit=500, saving_name=""):
        if not self.login():
            return

        myName= "籍籍无名哈撒给"
        player = self.search_lol_user(myName)[0]
        print(f'玩家id:{player.lol_id}|玩家昵称:{player.lol_nick}|所在大区:{LOL_GameArea[str(player.lol_area)]["name"]} |段位:{player.lol_rank}')

        player.id = id
        player.nickname = nickname

        infos=self.get_player_battle_infos(player, limit=limit)
        infos_name = self.infos_dir+"/"+ saving_name
        with open(infos_name,"wb") as fid:
            pickle.dump(infos,fid)


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

    def game_analysis(self):
        games_type=set([])
        games_mode=set([])
        for infos in tqdm(self.record):
            games_type.add(infos["game_type"])
            games_mode.add(infos["game_mode"])
        print(f"Game types: {games_type};games_mode{games_mode}")


if __name__ == '__main__':
    from config import  HEADERS as headers
    from config import LOGIN_DATA as login_data

    # id = "L16613047346631875848"
    # nickname = "VesperDevin"

    # id = "L18160673698990541216"
    # nickname = "DevinVesper"

    id = "L13500438156688788059"
    nickname = "籍籍无名哈撒给"

    limit=500
    data_dir="C:/Users/go2cl/Desktop/spider_wegame/battle_infos"
    saving_name = f"{nickname}_{limit}.pkl"
    # spider = Spider_WeGame(login_data, headers, data_dir)
    # spider.generate_record(nickname, id, limit, saving_name)

    recorder_path=data_dir+"/"+saving_name
    ana_recorder = Analysis(recorder_path)
    ana_recorder.game_analysis()
    ana_recorder.friend_analysis()
    ana_recorder.date_timestamp_analysis(200)
