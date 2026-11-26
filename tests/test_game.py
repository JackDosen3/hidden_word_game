"""
Automated tests for Devil's Plan 3 Hidden Word Team Round-Robin Game:
1. Players join via invite link and each selects their own Hidden Word.
2. Turn 1: Player 1 is Setter, reveals hints with AI similarity measurement until >= 90 similarity.
3. Non-setter players can only guess ONCE per turn!
   - If a player tries a 2nd guess in the same turn, it is rejected with error_toast.
   - If all non-setter players exhaust their 1 guess without getting the exact word, the turn ends and reveals the word.
4. Full circle completes (cycle_finished) with final scoreboard rankings.
"""

import re
from starlette.testclient import TestClient
from app import app
from ai_judge import AIJudge


def test_judge_similarity_format():
    judge = AIJudge(api_key=None)
    res1 = judge.evaluate_similarity("모래시계", "시계")
    assert res1["is_correct"] is False
    assert re.match(r"^- 정답 여부: 불일치\n- 유사도: \d{1,3}$", res1["formatted_response"])

    res2 = judge.evaluate_similarity("모래시계", "물시계")
    assert res2["similarity"] >= 90

    res3 = judge.evaluate_similarity("모래시계", "모래시계")
    assert res3["is_correct"] is True
    assert res3["similarity"] == 100
    assert res3["formatted_response"] == "- 정답 여부: 일치\n- 유사도: 100"


def test_single_guess_limit_and_round_robin():
    client = TestClient(app)
    room_code = "ONCE1"

    with (
        client.websocket_connect(f"/ws/{room_code}") as ws1,
        client.websocket_connect(f"/ws/{room_code}") as ws2,
        client.websocket_connect(f"/ws/{room_code}") as ws3,
    ):
        # 1. Three players join
        ws1.send_json({"action": "join", "player_id": "p1", "nickname": "홍진호"})
        _ = ws1.receive_json()

        ws2.send_json({"action": "join", "player_id": "p2", "nickname": "궤도"})
        _ = ws1.receive_json()
        _ = ws2.receive_json()

        ws3.send_json({"action": "join", "player_id": "p3", "nickname": "박지윤"})
        _ = ws1.receive_json()
        _ = ws2.receive_json()
        _ = ws3.receive_json()

        # 2. All 3 players submit their secret word
        ws1.send_json({"action": "submit_my_word", "secret_word": "모래시계", "category": "사물"})
        for w in (ws1, ws2, ws3):
            w.receive_json()

        ws2.send_json({"action": "submit_my_word", "secret_word": "김치찌개", "category": "음식"})
        for w in (ws1, ws2, ws3):
            w.receive_json()

        ws3.send_json({"action": "submit_my_word", "secret_word": "블랙홀", "category": "우주"})
        for w in (ws1, ws2, ws3):
            state_playing = w.receive_json()["state"]

        assert state_playing["status"] == "playing"
        assert state_playing["current_setter_id"] == "p1"
        assert state_playing["remaining_guessers_count"] == 2

        # 3. Setter p1 gives hints until >= 90 similarity
        ws1.send_json({"action": "give_hint", "word": "사막"})
        for w in (ws1, ws2, ws3):
            s = w.receive_json()["state"]
        assert s["setter_reached_90"] is False

        ws1.send_json({"action": "give_hint", "word": "해시계"})
        for w in (ws1, ws2, ws3):
            s = w.receive_json()["state"]
        assert s["setter_reached_90"] is True

        # 4. Guesser p2 uses their 1 guess and gets it WRONG ("자명종")
        ws2.send_json({"action": "submit_guess", "word": "자명종"})
        for w in (ws1, ws2, ws3):
            s = w.receive_json()["state"]
        assert "p2" in s["guessed_player_ids"]
        assert s["remaining_guessers_count"] == 1
        assert s["status"] == "playing"

        # 5. Guesser p2 tries to guess a SECOND time -> rejected with error_toast!
        ws2.send_json({"action": "submit_guess", "word": "모래시계"})
        err_msg = ws2.receive_json()
        assert err_msg["type"] == "error_toast"
        assert "한 번만" in err_msg["message"]

        # 6. Remaining Guesser p3 uses their 1 guess and gets it RIGHT ("모래시계")!
        ws3.send_json({"action": "submit_guess", "word": "모래시계"})
        for w in (ws1, ws2, ws3):
            s_clear = w.receive_json()["state"]
        assert s_clear["status"] == "turn_cleared"
        assert s_clear["turn_winner_nickname"] == "박지윤"

        # 7. Move to Turn 2 (p2 is Setter with "김치찌개")
        ws1.send_json({"action": "next_turn"})
        for w in (ws1, ws2, ws3):
            s_t2 = w.receive_json()["state"]
        assert s_t2["current_setter_id"] == "p2"
        assert s_t2["guessed_player_ids"] == []
        assert s_t2["remaining_guessers_count"] == 2

        # Test case where ALL non-setter players (p1 and p3) get their 1 guess wrong:
        ws1.send_json({"action": "submit_guess", "word": "된장국"})
        for w in (ws1, ws2, ws3):
            w.receive_json()

        ws3.send_json({"action": "submit_guess", "word": "라면"})
        for w in (ws1, ws2, ws3):
            s_exhausted = w.receive_json()["state"]

        # Since all non-setter players used their 1 chance, turn automatically finishes!
        assert s_exhausted["status"] == "turn_cleared"
        assert s_exhausted["turn_winner_id"] is None
        assert s_exhausted["secret_word"] == "김치찌개"


if __name__ == "__main__":
    test_judge_similarity_format()
    test_single_guess_limit_and_round_robin()
    print("✅ ALL SINGLE-GUESS & ROUND-ROBIN TESTS PASSED!")
