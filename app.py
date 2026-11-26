"""
Starlette/ASGI + WebSocket Multiplayer Server for Devil's Plan 3 'Hidden Word' Game.
Game Flow:
1. Teammates join via invite link (?room=CODE).
2. Each teammate selects their own secret 'Hidden Word' (히든 단어).
3. Players take turns one by one (round-robin, 한 바퀴 돌기) as the Setter (출제자).
4. During a turn:
   - The Setter reveals hint words for their Hidden Word.
   - AI measures the similarity (0~100) of each hint word.
   - The Setter MUST keep giving hints until a hint reaches >= 90 similarity!
   - Other teammates guess the Hidden Word (AI also measures similarity/exact match of guesses).
   - When a teammate guesses the exact Hidden Word (100점, 일치), points are awarded and the turn advances to the next teammate!
5. After everyone completes their turn (one full circle), the final scoreboard & winner are announced.
"""

import os
import socket
import random
import string
import time
from typing import Dict, List, Optional
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect

from ai_judge import AIJudge, normalize_word

judge = AIJudge()


def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_room_code(length: int = 5) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(length))


class Player:
    def __init__(self, player_id: str, nickname: str, websocket: WebSocket):
        self.player_id = player_id
        self.nickname = nickname
        self.websocket = websocket
        self.score: int = 0
        self.secret_word: str = ""
        self.category: str = ""
        self.word_ready: bool = False
        self.has_been_setter: bool = False
        self.joined_at = time.time()

    def to_public_dict(self, viewer_id: Optional[str] = None) -> Dict:
        data = {
            "player_id": self.player_id,
            "nickname": self.nickname,
            "score": self.score,
            "word_ready": self.word_ready,
            "has_been_setter": self.has_been_setter,
            "category": self.category,
        }
        if viewer_id == self.player_id:
            data["my_secret_word"] = self.secret_word
        return data


class Room:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.players: Dict[str, Player] = {}
        self.host_id: Optional[str] = None
        self.cycle_num: int = 1
        # Phases: "word_select" -> "playing" -> "turn_cleared" -> "cycle_finished"
        self.status: str = "word_select"
        self.turn_order: List[str] = []
        self.current_turn_idx: int = 0
        self.current_setter_id: Optional[str] = None

        # Current turn state
        self.setter_hints: List[Dict] = []     # Hints revealed by the current setter with AI similarity scores
        self.team_guesses: List[Dict] = []     # Guesses submitted by other teammates with AI similarity scores
        self.guessed_player_ids: List[str] = []  # Players who have used their single guess in this turn
        self.max_hint_similarity: int = 0      # Highest similarity among the setter's hints
        self.setter_reached_90: bool = False   # True once setter gives a hint with >= 90 similarity
        self.max_guess_similarity: int = 0     # Highest similarity among teammates' guesses
        self.turn_winner_id: Optional[str] = None
        self.turn_winner_nickname: Optional[str] = None
        self.turn_history: List[Dict] = []     # Summary of completed turns in this cycle

    def reset_for_new_cycle(self, reset_scores: bool = False):
        self.cycle_num += 1
        self.status = "word_select"
        self.turn_order = []
        self.current_turn_idx = 0
        self.current_setter_id = None
        self.setter_hints = []
        self.team_guesses = []
        self.guessed_player_ids = []
        self.max_hint_similarity = 0
        self.setter_reached_90 = False
        self.max_guess_similarity = 0
        self.turn_winner_id = None
        self.turn_winner_nickname = None
        self.turn_history = []
        for p in self.players.values():
            p.secret_word = ""
            p.category = ""
            p.word_ready = False
            p.has_been_setter = False
            if reset_scores:
                p.score = 0

    def start_cycle_turns(self) -> bool:
        # Ensure all players have a word; if someone didn't pick yet, assign a random one so game doesn't block
        for p in self.players.values():
            if not p.word_ready or not p.secret_word:
                sample = judge.get_word_suggestions(1)[0]
                p.secret_word = sample["word"]
                p.category = sample["category"]
                p.word_ready = True
            p.has_been_setter = False

        self.turn_order = list(self.players.keys())
        if not self.turn_order:
            return False
        self.current_turn_idx = 0
        self.turn_history = []
        self._init_current_turn()
        return True

    def _init_current_turn(self):
        # Advance until we find a connected player in turn_order
        while self.current_turn_idx < len(self.turn_order):
            candidate_id = self.turn_order[self.current_turn_idx]
            if candidate_id in self.players:
                self.current_setter_id = candidate_id
                break
            self.current_turn_idx += 1

        if self.current_turn_idx >= len(self.turn_order) or not self.current_setter_id:
            self.status = "cycle_finished"
            self.current_setter_id = None
            return

        self.status = "playing"
        self.setter_hints = []
        self.team_guesses = []
        self.guessed_player_ids = []
        self.max_hint_similarity = 0
        self.setter_reached_90 = False
        self.max_guess_similarity = 0
        self.turn_winner_id = None
        self.turn_winner_nickname = None

    def advance_to_next_turn(self):
        if self.current_setter_id and self.current_setter_id in self.players:
            self.players[self.current_setter_id].has_been_setter = True
        self.current_turn_idx += 1
        self._init_current_turn()

    def current_setter(self) -> Optional[Player]:
        if self.current_setter_id:
            return self.players.get(self.current_setter_id)
        return None

    def to_state_dict(self, viewer_id: Optional[str] = None) -> Dict:
        setter = self.current_setter()
        secret_word = setter.secret_word if setter else ""
        category = setter.category if setter else ""

        is_viewer_setter = bool(viewer_id and viewer_id == self.current_setter_id)
        can_see_secret = is_viewer_setter or self.status in ("turn_cleared", "cycle_finished")

        # Provide 90+ similarity guide words ONLY to the current setter so they never get stuck
        setter_guide = []
        if is_viewer_setter and secret_word:
            setter_guide = judge.get_setter_90_plus_guide(secret_word)

        # Combine hints + guesses into a unified chronological feed AND ranked feed
        all_events = sorted(
            self.setter_hints + self.team_guesses,
            key=lambda x: x["seq"]
        )
        ranked_words = sorted(
            self.setter_hints + self.team_guesses,
            key=lambda x: (-x["similarity"], x["seq"])
        )

        sorted_scoreboard = sorted(
            [p.to_public_dict(viewer_id=viewer_id) for p in self.players.values()],
            key=lambda x: (-x["score"], x["nickname"])
        )

        non_setter_ids = [pid for pid in self.players.keys() if pid != self.current_setter_id]
        remaining_guessers_count = sum(1 for pid in non_setter_ids if pid not in self.guessed_player_ids)

        return {
            "room_id": self.room_id,
            "host_id": self.host_id,
            "cycle_num": self.cycle_num,
            "status": self.status,
            "turn_order": self.turn_order,
            "current_turn_idx": self.current_turn_idx,
            "total_turns": len(self.turn_order),
            "current_setter_id": self.current_setter_id,
            "current_setter_nickname": setter.nickname if setter else None,
            "category": category or "자유 주제",
            "secret_word_length": len(secret_word) if secret_word else 0,
            "secret_word": secret_word if can_see_secret else None,
            "setter_guide_words": setter_guide,
            "setter_hints": self.setter_hints,
            "team_guesses": self.team_guesses,
            "guessed_player_ids": self.guessed_player_ids,
            "remaining_guessers_count": remaining_guessers_count,
            "all_events": all_events,
            "ranked_words": ranked_words,
            "max_hint_similarity": self.max_hint_similarity,
            "setter_reached_90": self.setter_reached_90,
            "max_guess_similarity": self.max_guess_similarity,
            "turn_winner_id": self.turn_winner_id,
            "turn_winner_nickname": self.turn_winner_nickname,
            "turn_history": self.turn_history,
            "players": [p.to_public_dict(viewer_id=viewer_id) for p in self.players.values()],
            "scoreboard": sorted_scoreboard,
            "all_words_ready": len(self.players) > 0 and all(p.word_ready for p in self.players.values()),
            "ready_count": sum(1 for p in self.players.values() if p.word_ready),
            "ai_live": judge.is_live_ai(),
        }


rooms: Dict[str, Room] = {}


def get_or_create_room(room_id: str) -> Room:
    code = room_id.upper().strip()
    if code not in rooms:
        rooms[code] = Room(code)
    return rooms[code]


async def broadcast_room_state(room: Room, event_banner: Optional[Dict] = None):
    dead_ids = []
    for pid, player in list(room.players.items()):
        try:
            payload = {
                "type": "room_state",
                "state": room.to_state_dict(viewer_id=pid),
            }
            if event_banner:
                payload["banner"] = event_banner
            await player.websocket.send_json(payload)
        except Exception:
            dead_ids.append(pid)

    for pid in dead_ids:
        room.players.pop(pid, None)


async def server_info(request: Request):
    lan_ip = get_lan_ip()
    port = request.url.port or 8080
    return JSONResponse({
        "lan_ip": lan_ip,
        "port": port,
        "ai_live": judge.is_live_ai(),
        "suggestions": judge.get_word_suggestions(6),
    })


async def word_suggestions_endpoint(request: Request):
    return JSONResponse({"suggestions": judge.get_word_suggestions(6)})


async def config_api_key(request: Request):
    body = await request.json()
    api_key = body.get("api_key", "")
    ok = judge.set_api_key(api_key)
    for r in rooms.values():
        await broadcast_room_state(r)
    return JSONResponse({"success": ok, "ai_live": judge.is_live_ai()})


async def direct_judge_endpoint(request: Request):
    body = await request.json()
    target_word = body.get("target_word", "")
    player_word = body.get("player_word", "")
    res = judge.evaluate_similarity(target_word, player_word)
    return JSONResponse(res)


async def websocket_endpoint(websocket: WebSocket):
    room_id = websocket.path_params["room_id"]
    await websocket.accept()
    room = get_or_create_room(room_id)
    player_id: Optional[str] = None

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "join":
                player_id = data.get("player_id") or "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
                nickname = (data.get("nickname") or "플레이어").strip()[:16]
                if player_id in room.players:
                    player = room.players[player_id]
                    player.nickname = nickname
                    player.websocket = websocket
                else:
                    player = Player(player_id=player_id, nickname=nickname, websocket=websocket)
                    room.players[player_id] = player
                    # If game is already playing, add new player to the end of turn_order
                    if room.status in ("playing", "turn_cleared") and player_id not in room.turn_order:
                        room.turn_order.append(player_id)

                if not room.host_id or room.host_id not in room.players:
                    room.host_id = player_id

                await broadcast_room_state(
                    room,
                    event_banner={"type": "info", "message": f"👋 '{nickname}' 님이 초대 링크를 통해 팀에 합류했습니다!"}
                )

            elif action == "submit_my_word":
                if not player_id or player_id not in room.players:
                    continue
                word = (data.get("secret_word") or "").strip()
                category = (data.get("category") or "자유 주제").strip()
                if not word:
                    continue
                p = room.players[player_id]
                p.secret_word = word
                p.category = category
                p.word_ready = True

                # Check if everyone in the room (>= 2 players) is ready while in word_select
                all_ready = len(room.players) >= 2 and all(pl.word_ready for pl in room.players.values())
                if room.status == "word_select" and all_ready:
                    room.start_cycle_turns()
                    setter = room.current_setter()
                    setter_name = setter.nickname if setter else "출제자"
                    await broadcast_room_state(
                        room,
                        event_banner={
                            "type": "round_start",
                            "message": f"🎉 모든 팀원이 히든 단어 선택을 완료했습니다! 1번째 출제자 [{setter_name}] 님의 턴을 시작합니다!"
                        }
                    )
                else:
                    await broadcast_room_state(
                        room,
                        event_banner={
                            "type": "info",
                            "message": f"✅ '{p.nickname}' 님이 자신의 히든 단어를 준비했습니다! ({sum(1 for pl in room.players.values() if pl.word_ready)}/{len(room.players)}명 완료)"
                        }
                    )

            elif action == "start_game":
                # Manual start button (even with 1+ players)
                if not player_id or player_id not in room.players:
                    continue
                room.start_cycle_turns()
                setter = room.current_setter()
                setter_name = setter.nickname if setter else "출제자"
                await broadcast_room_state(
                    room,
                    event_banner={
                        "type": "round_start",
                        "message": f"🎮 게임 시작! 첫 번째 출제자 [{setter_name}] 님은 유사도 90점 이상이 나올 때까지 단서/힌트를 공개해 주세요!"
                    }
                )

            elif action == "give_hint":
                # Current setter reveals a hint word for their secret word
                if not player_id or room.status != "playing":
                    continue
                if player_id != room.current_setter_id:
                    await websocket.send_json({
                        "type": "error_toast",
                        "message": "⚠️ 현재 턴의 출제자만 단서/힌트를 공개할 수 있습니다!"
                    })
                    continue

                hint_word = (data.get("word") or "").strip()
                if not hint_word:
                    continue

                setter = room.current_setter()
                if not setter or not setter.secret_word:
                    continue

                # Prevent setter from typing the exact secret word
                if normalize_word(hint_word) == normalize_word(setter.secret_word):
                    await websocket.send_json({
                        "type": "error_toast",
                        "message": "⚠️ 히든 단어(정답) 자체를 그대로 힌트로 공개할 수 없습니다! 관련 단서 단어를 입력해 주세요."
                    })
                    continue

                # Evaluate similarity between setter's secret word and setter's hint word
                eval_res = judge.evaluate_similarity(
                    setter.secret_word,
                    hint_word,
                    attempt_count=len(room.setter_hints) + 1
                )
                sim = eval_res["similarity"]
                if sim >= 100:
                    sim = 99
                    eval_res["similarity"] = 99
                    eval_res["is_correct"] = False
                    eval_res["match_text"] = "불일치"
                    eval_res["formatted_response"] = "- 정답 여부: 불일치\n- 유사도: 99"

                seq_num = len(room.setter_hints) + len(room.team_guesses) + 1
                hint_entry = {
                    "seq": seq_num,
                    "hint_num": len(room.setter_hints) + 1,
                    "kind": "hint",
                    "player_id": player_id,
                    "nickname": setter.nickname,
                    "word": hint_word,
                    "is_correct": False,
                    "match_text": "불일치",
                    "similarity": sim,
                    "formatted_response": eval_res["formatted_response"],
                    "timestamp": time.strftime("%H:%M:%S"),
                }
                room.setter_hints.append(hint_entry)

                if sim > room.max_hint_similarity:
                    room.max_hint_similarity = sim

                prev_reached_90 = room.setter_reached_90
                if room.max_hint_similarity >= 90:
                    room.setter_reached_90 = True

                if room.setter_reached_90 and not prev_reached_90:
                    banner = {
                        "type": "high_similarity",
                        "message": f"🔥 출제자 '{setter.nickname}' 님의 힌트 [{hint_word}] 유사도 {sim}점! (90점 이상 달성 완료!) 이제 팀원들이 히든 단어를 맞힐 차례입니다!"
                    }
                elif not room.setter_reached_90:
                    banner = {
                        "type": "hint_unlocked",
                        "message": f"💡 힌트 #{len(room.setter_hints)} 공개: [{hint_word}] → 유사도 {sim}점 (아직 90점 미달! 90점 이상 나올 때까지 출제자는 계속 힌트를 주세요!)"
                    }
                else:
                    banner = {
                        "type": "info",
                        "message": f"💡 추가 힌트 공개: [{hint_word}] → 유사도 {sim}점"
                    }

                await broadcast_room_state(room, event_banner=banner)

            elif action == "submit_guess":
                # Other teammates guess the current setter's secret word (ONLY ONCE per turn!)
                if not player_id or room.status != "playing":
                    continue
                if player_id == room.current_setter_id:
                    await websocket.send_json({
                        "type": "error_toast",
                        "message": "⚠️ 출제자는 직접 정답을 맞힐 수 없습니다! 단서/힌트를 공개해 주세요."
                    })
                    continue

                if player_id in room.guessed_player_ids:
                    await websocket.send_json({
                        "type": "error_toast",
                        "message": "⚠️ 출제자를 제외한 팀원은 한 턴에 정답을 딱 한 번만 말할 수 있습니다! (이미 기회 사용 완료)"
                    })
                    continue

                guess_word = (data.get("word") or "").strip()
                if not guess_word:
                    continue

                setter = room.current_setter()
                guesser = room.players.get(player_id)
                if not setter or not guesser or not setter.secret_word:
                    continue

                # Record that this player has used their single guess for this turn
                room.guessed_player_ids.append(player_id)

                eval_res = judge.evaluate_similarity(
                    setter.secret_word,
                    guess_word,
                    attempt_count=len(room.team_guesses)
                )
                sim = eval_res["similarity"]
                is_correct = eval_res["is_correct"]

                seq_num = len(room.setter_hints) + len(room.team_guesses) + 1
                guess_entry = {
                    "seq": seq_num,
                    "guess_num": len(room.team_guesses) + 1,
                    "kind": "guess",
                    "player_id": player_id,
                    "nickname": guesser.nickname,
                    "word": guess_word,
                    "is_correct": is_correct,
                    "match_text": eval_res["match_text"],
                    "similarity": sim,
                    "formatted_response": eval_res["formatted_response"],
                    "timestamp": time.strftime("%H:%M:%S"),
                }
                room.team_guesses.append(guess_entry)

                if sim > room.max_guess_similarity:
                    room.max_guess_similarity = sim

                if is_correct:
                    room.status = "turn_cleared"
                    room.turn_winner_id = player_id
                    room.turn_winner_nickname = guesser.nickname

                    # Score calculation:
                    guesser_pts = 120 if len(room.team_guesses) == 1 else 100
                    guesser.score += guesser_pts

                    setter_pts = 50 if room.setter_reached_90 else 30
                    setter.score += setter_pts

                    room.turn_history.append({
                        "turn_num": room.current_turn_idx + 1,
                        "setter_nickname": setter.nickname,
                        "secret_word": setter.secret_word,
                        "winner_nickname": guesser.nickname,
                        "hints_count": len(room.setter_hints),
                        "max_hint_sim": room.max_hint_similarity,
                    })

                    banner = {
                        "type": "cleared",
                        "message": f"🎉 정답 일치 (100점)! '{guesser.nickname}' 님이 단 한 번의 기회로 히든 단어 [{setter.secret_word}]를 맞혔습니다! (+{guesser_pts}점 획득, 출제자 +{setter_pts}점)"
                    }
                else:
                    # Check if all non-setter players have now used their 1 guess
                    non_setter_ids = [pid for pid in room.players.keys() if pid != room.current_setter_id]
                    all_exhausted = len(non_setter_ids) > 0 and all(pid in room.guessed_player_ids for pid in non_setter_ids)

                    if all_exhausted:
                        room.status = "turn_cleared"
                        room.turn_winner_id = None
                        room.turn_winner_nickname = "정답자 없음 (전원 1회 기회 소진)"
                        room.turn_history.append({
                            "turn_num": room.current_turn_idx + 1,
                            "setter_nickname": setter.nickname,
                            "secret_word": setter.secret_word,
                            "winner_nickname": "정답자 없음",
                            "hints_count": len(room.setter_hints),
                            "max_hint_sim": room.max_hint_similarity,
                        })
                        banner = {
                            "type": "warn",
                            "message": f"❌ '{guesser.nickname}' 님의 추측 [{guess_word}] 불일치 ({sim}점)! 모든 팀원이 1회 정답 기회를 모두 소진했습니다. 히든 단어는 [{setter.secret_word}] 였습니다!"
                        }
                    else:
                        rem = sum(1 for pid in non_setter_ids if pid not in room.guessed_player_ids)
                        banner = {
                            "type": "info",
                            "message": f"❌ '{guesser.nickname}' 님의 1회 정답 도전 [{guess_word}] → 유사도 {sim}점 (불일치, 기회 소진! 남은 도전자: {rem}명)"
                        }

                await broadcast_room_state(room, event_banner=banner)

            elif action == "next_turn":
                if not player_id or room.status not in ("playing", "turn_cleared"):
                    continue
                # If skipped before cleared, record in history
                if room.status == "playing":
                    setter = room.current_setter()
                    if setter:
                        room.turn_history.append({
                            "turn_num": room.current_turn_idx + 1,
                            "setter_nickname": setter.nickname,
                            "secret_word": setter.secret_word,
                            "winner_nickname": "미해결 (패스)",
                            "hints_count": len(room.setter_hints),
                            "max_hint_sim": room.max_hint_similarity,
                        })

                room.advance_to_next_turn()
                if room.status == "cycle_finished":
                    await broadcast_room_state(
                        room,
                        event_banner={
                            "type": "cleared",
                            "message": "🏆 모든 팀원의 출제 턴(한 바퀴)이 종료되었습니다! 최종 점수 순위를 확인하세요!"
                        }
                    )
                else:
                    setter = room.current_setter()
                    setter_name = setter.nickname if setter else "다음 출제자"
                    await broadcast_room_state(
                        room,
                        event_banner={
                            "type": "round_start",
                            "message": f"🔄 다음 차례! [{setter_name}] 님이 출제자입니다. 유사도 90점 이상이 나올 때까지 힌트를 공개해 주세요!"
                        }
                    )

            elif action == "new_cycle":
                if not player_id:
                    continue
                reset_scores = bool(data.get("reset_scores", False))
                room.reset_for_new_cycle(reset_scores=reset_scores)
                await broadcast_room_state(
                    room,
                    event_banner={
                        "type": "round_start",
                        "message": f"🎲 {room.cycle_num}번째 바퀴 시작! 각자 출제할 새로운 히든 단어를 선택해 주세요!"
                    }
                )

    except WebSocketDisconnect:
        if player_id and player_id in room.players:
            left_name = room.players[player_id].nickname
            room.players.pop(player_id, None)
            if room.host_id == player_id:
                room.host_id = next(iter(room.players.keys()), None)
            if room.current_setter_id == player_id and room.status == "playing":
                room.advance_to_next_turn()
            await broadcast_room_state(
                room,
                event_banner={"type": "info", "message": f"👋 '{left_name}' 님이 퇴장했습니다."}
            )


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)


async def index(request: Request):
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


routes = [
    Route("/", index, methods=["GET"]),
    Route("/api/server-info", server_info, methods=["GET"]),
    Route("/api/suggestions", word_suggestions_endpoint, methods=["GET"]),
    Route("/api/config-key", config_api_key, methods=["POST"]),
    Route("/api/judge", direct_judge_endpoint, methods=["POST"]),
    WebSocketRoute("/ws/{room_id}", websocket_endpoint),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(routes=routes)
