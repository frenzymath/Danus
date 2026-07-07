#!/usr/bin/env bash
# =============================================================================
# Danus services — start/stop/inspect the long-running services so they PERSIST
# beyond the session that launched them (a Claude Code session, an ssh shell…).
#
# Why setsid: a plain `… &` background job started from a transient shell gets
# reaped when that shell exits. `setsid` puts the service in its OWN session
# (reparented to init), with stdio detached — so it keeps running after the
# Claude Code session ends / the laptop disconnects.
#
#   bash scripts/services.sh up   verify
#   bash scripts/services.sh up   dashboard <project>
#   bash scripts/services.sh status
#   bash scripts/services.sh test                    # health-probe what's up
#   bash scripts/services.sh logs verify [-f]
#   bash scripts/services.sh down verify|dashboard|all
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
RUN="$DANUS_RUNTIME/run"; LOG="$DANUS_RUNTIME/logs"; mkdir -p "$RUN" "$LOG"

_pf(){ echo "$RUN/$1.pid"; }
_alive(){ local p; p="$(cat "$(_pf "$1")" 2>/dev/null || true)"; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

# autostart manifest — the `up` invocations to replay after a restart
# (scripts/recover.sh reads it). One `up`-arg-line per service.
AUTO="$RUN/autostart"
_auto_add(){ touch "$AUTO"; grep -qxF "$1" "$AUTO" 2>/dev/null || echo "$1" >> "$AUTO"; }
_auto_del(){ [ -f "$AUTO" ] || return 0; grep -vxF "$1" "$AUTO" > "$AUTO.tmp" 2>/dev/null || true; mv -f "$AUTO.tmp" "$AUTO" 2>/dev/null || true; }

# _spawn <name> <command…> : detach via setsid; the inner shell records its own
# pid then exec's the service, so the pidfile holds the real service pid (exec
# preserves the pid down the start-*.sh → python chain).
_spawn(){
  local name="$1"; shift
  local pf; pf="$(_pf "$name")"
  if _alive "$name"; then echo "[$name] already up (pid $(cat "$pf"))"; return 0; fi
  setsid bash -c "echo \$\$ > '$pf'; exec $*" >"$LOG/$name.log" 2>&1 </dev/null &
  sleep 1
  if _alive "$name"; then echo "[$name] up (pid $(cat "$pf"); log: runtime/logs/$name.log)";
  else echo "[$name] FAILED to start — see runtime/logs/$name.log"; tail -5 "$LOG/$name.log" 2>/dev/null; return 1; fi
}

_stop(){
  local name="$1" pf p; pf="$(_pf "$name")"
  p="$(cat "$pf" 2>/dev/null || true)"
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
    kill -TERM -"$p" 2>/dev/null || kill -TERM "$p" 2>/dev/null   # negative pid = whole session/group
    sleep 2; kill -0 "$p" 2>/dev/null && { kill -KILL -"$p" 2>/dev/null || kill -KILL "$p" 2>/dev/null; }
    echo "[$name] stopped (was pid $p)"
  else echo "[$name] not running"; fi
  rm -f "$pf"
}

case "${1:-}" in
  up)
    svc="${2:?usage: services.sh up verify|dashboard <project>}"
    case "$svc" in
      verify)    _spawn verify    "bash '$DANUS_ROOT/scripts/start-verify.sh'" && _auto_add "verify" ;;
      dashboard) proj="${3:?usage: services.sh up dashboard <project>}"
                 _spawn "dashboard-$proj" "bash '$DANUS_ROOT/scripts/start-dashboard.sh' '$proj'" && _auto_add "dashboard $proj" ;;
      *) echo "unknown service: $svc"; exit 1 ;;
    esac ;;
  down)
    case "${2:?usage: services.sh down verify|dashboard|all}" in
      all) for f in "$RUN"/*.pid; do [ -e "$f" ] && _stop "$(basename "$f" .pid)"; done; rm -f "$AUTO" ;;
      dashboard) for f in "$RUN"/dashboard-*.pid; do [ -e "$f" ] && _stop "$(basename "$f" .pid)"; done
                 [ -f "$AUTO" ] && grep -v '^dashboard ' "$AUTO" > "$AUTO.tmp" && mv -f "$AUTO.tmp" "$AUTO" ;;
      *) _stop "$2"; _auto_del "$2" ;;
    esac ;;
  status)
    echo "== Danus services =="
    shopt -s nullglob
    pids=("$RUN"/*.pid)
    [ ${#pids[@]} -eq 0 ] && { echo "  (none started via services.sh)"; }
    for f in "${pids[@]}"; do
      n="$(basename "$f" .pid)"
      if _alive "$n"; then printf "  up    %-18s pid %s\n" "$n" "$(cat "$f")"
      else printf "  down  %-18s (stale pidfile)\n" "$n"; fi
    done
    case "$(danus_verify_health)" in
      ours)    echo "verify: up on :$VERIFY_PORT (ours)" ;;
      foreign) echo "verify: :$VERIFY_PORT answered by a FOREIGN process (not ours) — another deployment holds this port; set a distinct VERIFY_PORT in config/danus.env" ;;
      stale)   echo "verify: down on :$VERIFY_PORT (stale pidfile)" ;;
      *)       echo "verify: down on :$VERIFY_PORT" ;;
    esac ;;
  test)
    echo "== probing services =="
    bash "$DANUS_ROOT/scripts/check-codex.sh" 2>/dev/null | sed 's/^/  codex: /' || true
    case "$(danus_verify_health)" in
      ours)    echo "  ok   verify  http://127.0.0.1:$VERIFY_PORT (ours)" ;;
      foreign) echo "  FAIL verify  :$VERIFY_PORT answered by a FOREIGN process (not ours) — set a distinct VERIFY_PORT" ;;
      *)       echo "  --   verify  down (services.sh up verify)" ;;
    esac ;;
  logs)
    n="${2:?usage: services.sh logs <service> [-f]}"; f="$LOG/$n.log"
    [ -e "$f" ] || { echo "no log: $f"; exit 1; }
    [ "${3:-}" = "-f" ] && exec tail -f "$f" || tail -50 "$f" ;;
  *)
    sed -n '2,21p' "$0" ;;
esac
