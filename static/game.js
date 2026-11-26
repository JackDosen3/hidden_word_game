// Devil's Plan 3 - Hidden Word Team Round-Robin Client

let ws = null;
let myPlayerId = localStorage.getItem("dp3_player_id") || ("p_" + Math.random().toString(36).substring(2, 10));
localStorage.setItem("dp3_player_id", myPlayerId);

let currentRoomId = "";
let currentRoomState = null;
let serverLanIp = "127.0.0.1";

window.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("/api/server-info");
    const info = await res.json();
    serverLanIp = info.lan_ip || "127.0.0.1";
    updateAiBadge(info.ai_live);
    renderSuggestionChips(info.suggestions || []);
  } catch (e) {
    console.warn("Failed to load server info", e);
  }

  const params = new URLSearchParams(window.location.search);
  const invitedRoom = params.get("room");
  const savedNick = localStorage.getItem("dp3_nickname") || "";
  if (savedNick) {
    document.getElementById("nicknameInput").value = savedNick;
  }

  if (invitedRoom) {
    document.getElementById("roomCodeInput").value = invitedRoom.toUpperCase();
    document.getElementById("inviteDetectedBadge").classList.remove("hidden");
  } else {
    generateNewRoomInInput();
  }
});

async function refreshSuggestions() {
  try {
    const res = await fetch("/api/suggestions");
    const data = await res.json();
    renderSuggestionChips(data.suggestions || []);
  } catch (e) {
    console.warn(e);
  }
}

function renderSuggestionChips(suggestions) {
  const container = document.getElementById("suggestionChips");
  if (!container) return;
  container.innerHTML = suggestions.map(item => `
    <button type="button" onclick="pickSuggestedWord('${escapeHtml(item.word)}', '${escapeHtml(item.category)}')"
      class="px-3 py-1.5 rounded-xl bg-zinc-800 hover:bg-amber-500/20 border border-zinc-700 hover:border-amber-400 text-xs font-bold text-zinc-200 hover:text-amber-300 transition">
      ${escapeHtml(item.word)} <span class="text-[10px] text-zinc-400">(${escapeHtml(item.category)})</span>
    </button>
  `).join("");
}

function pickSuggestedWord(word, category) {
  document.getElementById("mySecretWordInput").value = word;
  document.getElementById("myCategoryInput").value = category;
}

function updateAiBadge(isLive) {
  const badge = document.getElementById("aiBadge");
  if (!badge) return;
  if (isLive) {
    badge.textContent = "⚡ Gemini AI 실시간 유사도 측정";
    badge.className = "text-[11px] px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold";
  } else {
    badge.textContent = "🤖 AI 유사도 측정 가동 중";
    badge.className = "text-[11px] px-2.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 font-medium";
  }
}

function generateNewRoomInInput() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let code = "";
  for (let i = 0; i < 5; i++) {
    code += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  document.getElementById("roomCodeInput").value = code;
}

function getShareableInviteUrl(roomId) {
  const protocol = window.location.protocol;
  const host = window.location.hostname;
  const portPart = window.location.port ? `:${window.location.port}` : "";
  const effectiveHost = (host === "localhost" || host === "127.0.0.1") && serverLanIp !== "127.0.0.1"
    ? serverLanIp
    : host;
  return `${protocol}//${effectiveHost}${portPart}/?room=${encodeURIComponent(roomId)}`;
}

async function copyInviteLink() {
  if (!currentRoomId) return;
  const url = getShareableInviteUrl(currentRoomId);
  try {
    await navigator.clipboard.writeText(url);
    showToast("🔗 팀원 초대 링크가 복사되었습니다! 팀원들에게 공유하세요.", "success");
  } catch (e) {
    prompt("아래 초대 링크를 복사해 팀원에게 공유하세요:", url);
  }
}

function joinGameRoom() {
  const nickInput = document.getElementById("nicknameInput");
  const roomInput = document.getElementById("roomCodeInput");

  const nickname = (nickInput.value || "").trim() || ("팀원" + Math.floor(Math.random() * 90 + 10));
  let roomCode = (roomInput.value || "").trim().toUpperCase();
  if (!roomCode) {
    generateNewRoomInInput();
    roomCode = document.getElementById("roomCodeInput").value;
  }

  localStorage.setItem("dp3_nickname", nickname);
  currentRoomId = roomCode;

  const newUrl = `${window.location.pathname}?room=${encodeURIComponent(roomCode)}`;
  window.history.replaceState({ path: newUrl }, "", newUrl);

  connectWebSocket(roomCode, nickname);
}

function connectWebSocket(roomId, nickname) {
  if (ws) {
    ws.close();
  }
  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProto}//${window.location.host}/ws/${encodeURIComponent(roomId)}`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    ws.send(JSON.stringify({
      action: "join",
      player_id: myPlayerId,
      nickname: nickname
    }));
    document.getElementById("lobbyScreen").classList.add("hidden");
    document.getElementById("gameScreen").classList.remove("hidden");
    document.getElementById("roomInviteBox").classList.remove("hidden");
    document.getElementById("roomInviteBox").classList.add("flex");
    document.getElementById("headerRoomCode").textContent = roomId;
    document.getElementById("inviteUrlDisplay").textContent = getShareableInviteUrl(roomId);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "room_state") {
      currentRoomState = data.state;
      renderRoomState(data.state);
      if (data.banner) {
        handleBanner(data.banner);
      }
    } else if (data.type === "error_toast") {
      showToast(data.message, "warn");
    }
  };

  ws.onclose = () => {
    showToast("서버 연결이 끊어졌습니다. 페이지를 새로고침하면 재접속됩니다.", "warn");
  };
}

function handleBanner(banner) {
  if (!banner || !banner.message) return;
  if (banner.type === "cleared") {
    showToast(banner.message, "cleared");
  } else if (banner.type === "high_similarity") {
    showToast(banner.message, "critical");
  } else if (banner.type === "hint_unlocked") {
    showToast(banner.message, "hint");
  } else {
    showToast(banner.message, "info");
  }
}

function renderRoomState(state) {
  updateAiBadge(state.ai_live);

  // Cycle & Turn Progress
  document.getElementById("cycleBadge").textContent = `${state.cycle_num || 1}바퀴째 진행 중`;
  if (state.status === "word_select") {
    document.getElementById("turnProgressText").textContent =
      `히든 단어 선택 중 (${state.ready_count}/${state.players.length}명 완료)`;
  } else if (state.status === "cycle_finished") {
    document.getElementById("turnProgressText").textContent = `한 바퀴 완료! 최종 결과 발표`;
  } else {
    document.getElementById("turnProgressText").textContent =
      `출제 턴 ${state.current_turn_idx + 1} / ${state.total_turns} (${state.current_setter_nickname || '-'} 출제 중)`;
  }

  // Render Top Turn Order & Scoreboard Strip
  const stripEl = document.getElementById("turnOrderStrip");
  const orderedPlayers = state.turn_order && state.turn_order.length > 0
    ? state.turn_order.map(pid => state.players.find(p => p.player_id === pid)).filter(Boolean)
    : state.players;

  stripEl.innerHTML = orderedPlayers.map((p, idx) => {
    const isMe = p.player_id === myPlayerId;
    const isCurrentSetter = state.status !== "word_select" && state.status !== "cycle_finished" && p.player_id === state.current_setter_id;
    const usedGuess = (state.guessed_player_ids || []).includes(p.player_id);
    const isTurnWinner = state.turn_winner_id === p.player_id;
    let roleTag = "";
    if (state.status === "word_select") {
      roleTag = p.word_ready
        ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold">준비완료</span>`
        : `<span class="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">선택중</span>`;
    } else if (isCurrentSetter) {
      roleTag = `<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500 text-black font-black">출제 중 🔥</span>`;
    } else if (isTurnWinner) {
      roleTag = `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-400 text-black font-black">🏆 정답 적중!</span>`;
    } else if (usedGuess) {
      roleTag = `<span class="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">❌ 1회 기회소진</span>`;
    } else {
      roleTag = `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 font-bold">🎯 기회 1회 남음</span>`;
    }

    return `
      <div class="p-2.5 rounded-xl border transition ${
        isCurrentSetter
          ? 'bg-amber-950/40 border-amber-400 shadow-md shadow-amber-500/10'
          : isMe
          ? 'bg-zinc-900 border-amber-500/40'
          : 'bg-black/50 border-zinc-800'
      }">
        <div class="flex items-center justify-between gap-1 mb-1">
          <span class="text-[11px] font-bold text-zinc-400">#${idx + 1}</span>
          ${roleTag}
        </div>
        <div class="flex items-center justify-between gap-1">
          <span class="text-xs md:text-sm font-black text-white truncate">
            ${escapeHtml(p.nickname)} ${isMe ? '<span class="text-amber-400 text-[10px]">(나)</span>' : ''}
          </span>
          <span class="mono text-xs font-extrabold text-amber-400">${p.score}점</span>
        </div>
      </div>
    `;
  }).join("");

  // Toggle between the 3 main stages
  const wordSelectStage = document.getElementById("wordSelectStage");
  const playingStage = document.getElementById("playingStage");
  const cycleFinishedStage = document.getElementById("cycleFinishedStage");

  if (state.status === "word_select") {
    wordSelectStage.classList.remove("hidden");
    playingStage.classList.add("hidden");
    cycleFinishedStage.classList.add("hidden");
    renderWordSelectStage(state);
  } else if (state.status === "cycle_finished") {
    wordSelectStage.classList.add("hidden");
    playingStage.classList.add("hidden");
    cycleFinishedStage.classList.remove("hidden");
    renderCycleFinishedStage(state);
  } else {
    wordSelectStage.classList.add("hidden");
    playingStage.classList.remove("hidden");
    cycleFinishedStage.classList.add("hidden");
    renderPlayingStage(state);
  }
}

function renderWordSelectStage(state) {
  const me = state.players.find(p => p.player_id === myPlayerId);
  const banner = document.getElementById("mySelectedWordBanner");
  const textEl = document.getElementById("mySelectedWordText");

  if (me && me.word_ready && me.my_secret_word) {
    banner.classList.remove("hidden");
    textEl.textContent = `내가 등록한 히든 단어: [${me.my_secret_word}] (${me.category || '자유 주제'})`;
  } else {
    banner.classList.add("hidden");
  }

  const listEl = document.getElementById("wordSelectPlayerList");
  listEl.innerHTML = state.players.map(p => `
    <div class="flex items-center justify-between px-4 py-3 rounded-xl bg-black/60 border ${p.word_ready ? 'border-emerald-500/40' : 'border-zinc-800'}">
      <div class="flex items-center gap-2.5">
        <span class="w-2.5 h-2.5 rounded-full ${p.word_ready ? 'bg-emerald-400' : 'bg-amber-400 animate-pulse'}"></span>
        <span class="font-bold text-sm text-white">${escapeHtml(p.nickname)}</span>
        ${p.player_id === myPlayerId ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold">나</span>' : ''}
      </div>
      <span class="text-xs font-extrabold ${p.word_ready ? 'text-emerald-400' : 'text-amber-300'}">
        ${p.word_ready ? '✅ 히든 단어 선택 완료' : '⏳ 단어 고르는 중...'}
      </span>
    </div>
  `).join("");
}

function renderPlayingStage(state) {
  const isMeSetter = state.current_setter_id === myPlayerId;
  const isTurnCleared = state.status === "turn_cleared";
  const hasUsedMyGuess = (state.guessed_player_ids || []).includes(myPlayerId);

  document.getElementById("turnNumberBadge").textContent = `TURN ${state.current_turn_idx + 1} / ${state.total_turns}`;
  document.getElementById("currentSetterName").textContent =
    `${state.current_setter_nickname || '-'}${isMeSetter ? ' (나)' : ''}`;
  document.getElementById("turnCategoryText").textContent = state.category || "자유 주제";
  document.getElementById("turnLengthText").textContent = state.secret_word_length ? `${state.secret_word_length}글자` : "-";

  // Render Secret Word Slots
  const slotsEl = document.getElementById("secretWordSlots");
  if (state.secret_word) {
    const chars = Array.from(state.secret_word);
    slotsEl.innerHTML = chars.map(ch => `
      <div class="w-12 h-14 rounded-xl ${
        isTurnCleared
          ? 'bg-gradient-to-b from-emerald-400 to-teal-500 text-black'
          : 'bg-amber-950/80 border-2 border-amber-400 text-amber-300'
      } flex items-center justify-center text-xl font-black shadow-lg">
        ${escapeHtml(ch)}
      </div>
    `).join("");
  } else {
    const len = state.secret_word_length || 3;
    let html = "";
    for (let i = 0; i < len; i++) {
      html += `
        <div class="w-12 h-14 rounded-xl bg-zinc-900 border-2 border-amber-500/40 flex items-center justify-center text-xl font-black text-amber-400">
          ?
        </div>
      `;
    }
    slotsEl.innerHTML = html;
  }

  // Setter's 90-point Hint Similarity Gauge
  const maxHintSim = state.max_hint_similarity || 0;
  document.getElementById("maxHintSimText").textContent = `${maxHintSim}점`;
  document.getElementById("hintSimProgressBar").style.width = `${Math.min(100, maxHintSim)}%`;

  const turnHeaderCard = document.getElementById("turnHeaderCard");
  const ruleBox = document.getElementById("turnRuleStatusBox");
  const nextTurnBox = document.getElementById("nextTurnBox");

  if (isTurnCleared) {
    turnHeaderCard.className = "bg-zinc-900/90 border-2 border-emerald-400 rounded-2xl p-5 shadow-lg shadow-emerald-500/10";
    ruleBox.className = "mt-3 text-xs px-3.5 py-2.5 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 font-bold";
    if (state.turn_winner_id) {
      ruleBox.textContent = `🎉 '${state.turn_winner_nickname}' 님이 단 1번의 기회로 히든 단어 [${state.secret_word}]를 맞혔습니다!`;
      document.getElementById("turnResultSummaryText").textContent =
        `🏆 정답자: ${state.turn_winner_nickname} / 출제자: ${state.current_setter_nickname} (+${state.setter_reached_90 ? 50 : 30}점)`;
    } else {
      ruleBox.textContent = `❌ 모든 팀원이 1회 정답 기회를 모두 소진했습니다! 히든 단어는 [${state.secret_word}] 였습니다.`;
      document.getElementById("turnResultSummaryText").textContent =
        `🔓 정답자 없음 (히든 단어: ${state.secret_word}) — 다음 팀원 출제 차례로 이동하세요!`;
    }
    nextTurnBox.classList.remove("hidden");
  } else if (state.setter_reached_90) {
    turnHeaderCard.className = "bg-zinc-900/90 border-2 border-red-500 critical-glow rounded-2xl p-5";
    ruleBox.className = "mt-3 text-xs px-3.5 py-2.5 rounded-xl bg-red-500/20 border border-red-500/40 text-red-200 font-bold";
    ruleBox.textContent = `🔥 출제자가 90점 이상 유사도 힌트(${maxHintSim}점)를 공개했습니다! 팀원들은 1번뿐인 정답 기회를 사용해 히든 단어를 맞혀보세요!`;
    nextTurnBox.classList.add("hidden");
  } else {
    turnHeaderCard.className = "bg-zinc-900/90 gold-border gold-glow rounded-2xl p-5";
    ruleBox.className = "mt-3 text-xs px-3.5 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 font-semibold";
    ruleBox.textContent = isMeSetter
      ? `⏳ 현재 내 힌트 최고 유사도 ${maxHintSim}점 (90점 미달) — 유사도 90점 이상이 나올 때까지 계속 단서/힌트를 공개하세요!`
      : `⏳ 출제자(${state.current_setter_nickname})가 유사도 90점 이상이 나올 때까지 단서/힌트를 공개하고 있습니다! (현재 최고 힌트: ${maxHintSim}점)`;
    nextTurnBox.classList.add("hidden");
  }

  // Toggle Setter Input vs Guesser Input
  const setterCard = document.getElementById("setterActionCard");
  const guesserCard = document.getElementById("guesserActionCard");
  const guesserFormBox = document.getElementById("guesserFormBox");
  const guesserUsedBox = document.getElementById("guesserUsedBox");

  if (isTurnCleared) {
    setterCard.classList.add("hidden");
    guesserCard.classList.add("hidden");
  } else if (isMeSetter) {
    setterCard.classList.remove("hidden");
    guesserCard.classList.add("hidden");
    const guideContainer = document.getElementById("setterGuideChips");
    const guides = state.setter_guide_words || [];
    guideContainer.innerHTML = guides.map(w => `
      <button type="button" onclick="quickSendSetterHint('${escapeHtml(w)}')"
        class="px-2.5 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500 hover:text-black border border-amber-400/40 text-amber-200 font-bold text-xs transition">
        + "${escapeHtml(w)}" (90점+ 단서)
      </button>
    `).join("");
  } else {
    setterCard.classList.add("hidden");
    guesserCard.classList.remove("hidden");
    if (hasUsedMyGuess) {
      guesserFormBox.classList.add("hidden");
      guesserUsedBox.classList.remove("hidden");
      document.getElementById("remainingGuessersBadge").textContent =
        `남은 도전자: ${state.remaining_guessers_count ?? 0}명`;
      document.getElementById("guesserSubStatus").textContent =
        "이번 턴 정답 기회(1회)를 이미 사용했습니다";
    } else {
      guesserFormBox.classList.remove("hidden");
      guesserUsedBox.classList.add("hidden");
      document.getElementById("guesserSubStatus").textContent = state.setter_reached_90
        ? "🔥 90점 이상 결정적 힌트가 나왔습니다! 1번뿐인 기회로 지금 정답을 맞히세요!"
        : "출제자가 90점 이상 힌트를 줄 때까지 기다렸다가 1번의 기회를 쓰는 것을 추천합니다!";
    }
  }

  // Render Setter Hints List
  const hintsListEl = document.getElementById("setterHintsList");
  const hints = state.setter_hints || [];
  document.getElementById("setterHintCountBadge").textContent = `${hints.length}개 공개됨`;

  if (hints.length === 0) {
    hintsListEl.innerHTML = `<div class="text-xs text-zinc-500 text-center py-6">아직 출제자가 공개한 힌트가 없습니다.</div>`;
  } else {
    hintsListEl.innerHTML = [...hints].reverse().map(h => {
      const is90 = h.similarity >= 90;
      return `
        <div class="p-3.5 rounded-xl ${is90 ? 'bg-red-950/50 border-2 border-red-400 animate-pop' : 'bg-black/65 border border-amber-500/30 animate-pop'} flex items-center justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-[11px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300">
                힌트 #${h.hint_num}
              </span>
              <span class="text-base font-black text-white">"${escapeHtml(h.word)}"</span>
              ${is90 ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-red-500 text-white font-black">90점+ 달성 🔥</span>' : ''}
            </div>
            <div class="mono text-xs text-zinc-400 mt-1">
              정답 여부: 불일치 · 유사도: <strong class="${is90 ? 'text-red-300' : 'text-amber-300'}">${h.similarity}점</strong>
            </div>
          </div>
          <div class="text-right">
            <span class="mono text-sm px-3 py-1.5 rounded-xl font-black ${
              is90 ? 'bg-red-500 text-white' : h.similarity >= 75 ? 'bg-amber-500 text-black' : 'bg-zinc-800 text-zinc-200'
            }">
              ${h.similarity}점
            </span>
          </div>
        </div>
      `;
    }).join("");
  }

  // Render Latest AI Judge Output Card (Exact Requested Format)
  const latestJudgeBox = document.getElementById("latestJudgeBox");
  const latestEventMeta = document.getElementById("latestEventMeta");
  const allEvents = state.all_events || [];
  if (allEvents.length > 0) {
    const last = allEvents[allEvents.length - 1];
    const kindLabel = last.kind === "hint" ? "출제자 힌트" : "팀원 추측";
    latestEventMeta.textContent = `[${kindLabel}] ${last.nickname}: "${last.word}"`;
    latestJudgeBox.textContent = last.formatted_response;
    if (last.is_correct) {
      latestJudgeBox.className = "p-4 rounded-xl bg-emerald-950/60 border-2 border-emerald-400 mono text-sm md:text-base font-bold leading-relaxed text-emerald-300 whitespace-pre-line";
    } else if (last.similarity >= 90) {
      latestJudgeBox.className = "p-4 rounded-xl bg-red-950/60 border-2 border-red-400 mono text-sm md:text-base font-bold leading-relaxed text-red-300 whitespace-pre-line";
    } else {
      latestJudgeBox.className = "p-4 rounded-xl bg-black/90 border border-amber-500/40 mono text-sm md:text-base leading-relaxed text-amber-300 whitespace-pre-line";
    }
  } else {
    latestEventMeta.textContent = "첫 힌트/추측 대기 중";
    latestJudgeBox.textContent = "- 정답 여부: 대기 중\n- 유사도: 0";
    latestJudgeBox.className = "p-4 rounded-xl bg-black/90 border border-zinc-800 mono text-sm md:text-base leading-relaxed text-zinc-400 whitespace-pre-line";
  }

  // Render Teammates' Guesses List
  const guessesEl = document.getElementById("teamGuessesList");
  const guesses = state.team_guesses || [];
  if (guesses.length === 0) {
    guessesEl.innerHTML = `<div class="text-xs text-zinc-500 text-center py-6">아직 팀원들이 입력한 정답 추측이 없습니다.</div>`;
  } else {
    guessesEl.innerHTML = [...guesses].reverse().map(g => `
      <div class="p-3 rounded-xl bg-black/60 border ${g.is_correct ? 'border-emerald-400 bg-emerald-950/30' : 'border-zinc-800'} flex items-center justify-between gap-2">
        <div>
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold text-emerald-400">${escapeHtml(g.nickname)}</span>
            <span class="text-sm font-black text-white">"${escapeHtml(g.word)}"</span>
          </div>
          <div class="mono text-xs text-zinc-400 mt-0.5">
            정답 여부: <strong class="${g.is_correct ? 'text-emerald-400' : 'text-zinc-300'}">${g.match_text}</strong> · 유사도: <strong class="text-amber-300">${g.similarity}</strong>
          </div>
        </div>
        <span class="mono text-xs px-2.5 py-1 rounded-lg font-extrabold ${
          g.is_correct ? 'bg-emerald-500 text-black' : g.similarity >= 90 ? 'bg-red-500 text-white' : 'bg-zinc-800 text-zinc-300'
        }">
          ${g.similarity}점
        </span>
      </div>
    `).join("");
  }

  // Render Ranked Words List
  const rankedEl = document.getElementById("rankedWordsList");
  const ranked = state.ranked_words || [];
  if (ranked.length === 0) {
    rankedEl.innerHTML = `<div class="text-xs text-zinc-500 text-center py-4">기록 없음</div>`;
  } else {
    rankedEl.innerHTML = ranked.slice(0, 10).map((item, idx) => `
      <div class="flex items-center justify-between px-3 py-2 rounded-lg ${item.similarity >= 90 ? 'bg-red-950/40 border border-red-500/40' : 'bg-black/40 border border-zinc-800/80'} text-xs">
        <div class="flex items-center gap-2 truncate">
          <span class="mono font-bold text-amber-400">#${idx + 1}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded ${item.kind === 'hint' ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'}">
            ${item.kind === 'hint' ? '힌트' : '추측'}
          </span>
          <span class="font-bold text-white truncate">${escapeHtml(item.word)}</span>
          <span class="text-[11px] text-zinc-500">(${escapeHtml(item.nickname)})</span>
        </div>
        <span class="mono font-extrabold ${item.similarity >= 90 ? 'text-red-400' : 'text-amber-300'}">${item.similarity}점</span>
      </div>
    `).join("");
  }
}

function renderCycleFinishedStage(state) {
  const boardEl = document.getElementById("finalScoreboardList");
  const scoreboard = state.scoreboard || [];
  boardEl.innerHTML = scoreboard.map((p, idx) => {
    const medal = idx === 0 ? "🥇 1위" : idx === 1 ? "🥈 2위" : idx === 2 ? "🥉 3위" : `${idx + 1}위`;
    return `
      <div class="flex items-center justify-between px-5 py-3.5 rounded-xl ${
        idx === 0 ? 'bg-gradient-to-r from-amber-500/25 to-yellow-500/10 border-2 border-amber-400' : 'bg-black/60 border border-zinc-800'
      }">
        <div class="flex items-center gap-3">
          <span class="font-black text-sm ${idx === 0 ? 'text-amber-400' : 'text-zinc-300'}">${medal}</span>
          <span class="text-base font-black text-white">${escapeHtml(p.nickname)}</span>
        </div>
        <span class="mono text-lg font-black text-amber-400">${p.score} pts</span>
      </div>
    `;
  }).join("");

  const histEl = document.getElementById("cycleHistoryList");
  const history = state.turn_history || [];
  if (history.length === 0) {
    histEl.innerHTML = `<div class="text-xs text-zinc-500 text-center py-3">기록이 없습니다.</div>`;
  } else {
    histEl.innerHTML = history.map(h => `
      <div class="flex flex-wrap items-center justify-between px-4 py-2.5 rounded-xl bg-black/50 border border-zinc-800 text-xs">
        <div>
          <span class="text-zinc-400 font-bold">TURN ${h.turn_num}</span> ·
          출제자 <strong class="text-amber-300">${escapeHtml(h.setter_nickname)}</strong>의 히든 단어:
          <strong class="text-white text-sm">[${escapeHtml(h.secret_word)}]</strong>
        </div>
        <div class="text-zinc-300">
          최고 힌트 유사도 <strong class="text-red-300">${h.max_hint_sim}점</strong> ·
          정답자: <strong class="text-emerald-400">${escapeHtml(h.winner_nickname)}</strong>
        </div>
      </div>
    `).join("");
  }
}

// Actions
function submitMySecretWord(e) {
  e.preventDefault();
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const word = (document.getElementById("mySecretWordInput").value || "").trim();
  const category = (document.getElementById("myCategoryInput").value || "").trim() || "자유 주제";
  if (!word) {
    showToast("출제할 나의 [히든 단어]를 입력하거나 추천 단어를 클릭해 주세요!", "warn");
    return;
  }
  ws.send(JSON.stringify({
    action: "submit_my_word",
    secret_word: word,
    category: category
  }));
}

function forceStartGame() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  // If user typed a word in the input box but didn't click save yet, submit it first
  const word = (document.getElementById("mySecretWordInput").value || "").trim();
  const category = (document.getElementById("myCategoryInput").value || "").trim() || "자유 주제";
  if (word) {
    ws.send(JSON.stringify({
      action: "submit_my_word",
      secret_word: word,
      category: category
    }));
  }
  ws.send(JSON.stringify({ action: "start_game" }));
}

function handleGiveHint(e) {
  e.preventDefault();
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const input = document.getElementById("setterHintWordInput");
  const word = (input.value || "").trim();
  if (!word) return;
  ws.send(JSON.stringify({
    action: "give_hint",
    word: word
  }));
  input.value = "";
  input.focus();
}

function quickSendSetterHint(word) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({
    action: "give_hint",
    word: word
  }));
}

function handleGuessSubmit(e) {
  e.preventDefault();
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const input = document.getElementById("teamGuessInput");
  const word = (input.value || "").trim();
  if (!word) return;
  ws.send(JSON.stringify({
    action: "submit_guess",
    word: word
  }));
  input.value = "";
  input.focus();
}

function goToNextTurn() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ action: "next_turn" }));
}

function startNextCycle(resetScores) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  document.getElementById("mySecretWordInput").value = "";
  document.getElementById("myCategoryInput").value = "";
  refreshSuggestions();
  ws.send(JSON.stringify({
    action: "new_cycle",
    reset_scores: resetScores
  }));
}

// API Key Modal
function openApiKeyModal() {
  const modal = document.getElementById("apiKeyModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function closeApiKeyModal() {
  const modal = document.getElementById("apiKeyModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

async function saveApiKey() {
  const key = (document.getElementById("apiKeyInput").value || "").trim();
  try {
    const res = await fetch("/api/config-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key })
    });
    const data = await res.json();
    updateAiBadge(data.ai_live);
    closeApiKeyModal();
    if (data.ai_live) {
      showToast("✅ Gemini API 키가 적용되었습니다!", "success");
    } else {
      showToast("🤖 기본 AI 시맨틱 측정 모드로 동작합니다.", "info");
    }
  } catch (e) {
    showToast("API 키 저장 중 오류가 발생했습니다.", "warn");
  }
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const el = document.createElement("div");
  let style = "bg-zinc-900 border-amber-500/40 text-zinc-100";
  if (type === "cleared") {
    style = "bg-emerald-950/95 border-emerald-400 text-emerald-200";
  } else if (type === "critical") {
    style = "bg-red-950/95 border-red-400 text-red-200";
  } else if (type === "hint") {
    style = "bg-amber-950/95 border-amber-400 text-amber-200";
  } else if (type === "warn") {
    style = "bg-rose-950/95 border-rose-400 text-rose-200";
  }
  el.className = `pointer-events-auto px-4 py-3 rounded-xl border shadow-xl text-xs font-bold animate-pop ${style}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 4200);
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
