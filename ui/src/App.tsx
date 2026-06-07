import { useState, useCallback, useEffect } from "react";
import { IconSparkles } from "@tabler/icons-react";
import { useRoomStore } from "./store.ts";
import { getEvents, getSnapshot, getRoom, set401Handler, probeAuth, logout } from "./api/client.ts";
import { useAuthStore } from "./authStore.ts";
import { RoomPicker } from "./components/RoomPicker.tsx";
import { RoomCreate } from "./components/RoomCreate.tsx";
import { RoomView } from "./components/RoomView.tsx";
import { LoginPage } from "./components/LoginPage.tsx";
import { NavBar } from "./components/NavBar.tsx";
import { PluginsPage } from "./components/PluginsPage.tsx";
import { ConfigPage } from "./components/ConfigPage.tsx";
import type { NavView } from "./components/NavBar.tsx";
import styles from "./App.module.css";

/**
 * Leave summary — shown when user leaves a room (§6.4 pattern 5 离开对称).
 * Derives a humanized summary from the snapshot (decisions + event count).
 * No raw vocabulary is surfaced here.
 */
interface LeaveSummary {
  roomId: string;
  eventCountOnLeave: number;
  decisionCount: number;
}

export default function App() {
  const roomId = useRoomStore((s) => s.roomId);
  const reset = useRoomStore((s) => s.reset);
  const [leaveSummary, setLeaveSummary] = useState<LeaveSummary | null>(null);
  const [view, setView] = useState<NavView>("lobby");

  const { status: authStatus, userId } = useAuthStore();
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated);
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);

  // Wire global 401 handler — any API call that 401s redirects to login.
  useEffect(() => {
    set401Handler(setUnauthenticated);
    return () => set401Handler(null);
  }, [setUnauthenticated]);

  // Auth probe on mount: hit a protected endpoint; 401 → login, else → authenticated.
  useEffect(() => {
    probeAuth().then((authed) => {
      if (authed) setAuthenticated("");
      else setUnauthenticated();
    });
  }, [setAuthenticated, setUnauthenticated]);

  const handleLeave = useCallback(async () => {
    if (!roomId) return;
    try {
      const snap = await getSnapshot(roomId);
      setLeaveSummary({
        roomId,
        eventCountOnLeave: snap.event_count,
        decisionCount: snap.decision_count,
      });
    } catch {
      setLeaveSummary({ roomId, eventCountOnLeave: 0, decisionCount: 0 });
    }
    reset();
  }, [roomId, reset]);

  const handleReturn = useCallback(
    async (returnRoomId: string) => {
      if (!leaveSummary) return;
      const setRoom = useRoomStore.getState().setRoom;
      try {
        const [events, room] = await Promise.all([
          getEvents(returnRoomId),
          getSnapshot(returnRoomId),
        ]);
        const newEvents = events.length - leaveSummary.eventCountOnLeave;
        setRoom(returnRoomId, room.room_type as Parameters<typeof setRoom>[1]);
        if (newEvents > 0) {
          alert(`离开后有 ${newEvents} 条新消息`);
        }
      } catch {
        const roomData = await getRoom(returnRoomId);
        setRoom(returnRoomId, roomData.type);
      }
      setLeaveSummary(null);
    },
    [leaveSummary],
  );

  const handleLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      // Logout failed silently — clear local auth state regardless.
    }
    setUnauthenticated();
  }, [setUnauthenticated]);

  // Loading state while auth probe runs.
  if (authStatus === "checking") {
    return (
      <div className={styles.app} style={{ justifyContent: "center", alignItems: "center" }}>
        <div className={styles.lobbyBrand}>
          <div className={styles.avatar}>
            <IconSparkles size={18} />
          </div>
          <span className={styles.wordmark}>Orchestrator</span>
        </div>
      </div>
    );
  }

  if (authStatus === "unauthenticated") {
    return <LoginPage />;
  }

  // Authenticated — room view takes over the full screen.
  if (roomId) {
    return (
      <div className={styles.app}>
        <RoomView onLeave={() => void handleLeave()} />
      </div>
    );
  }

  return (
    <div className={styles.app}>
      <NavBar view={view} onView={setView} userId={userId} onLogout={() => void handleLogout()} />

      {view === "plugins" && <PluginsPage />}
      {view === "config" && <ConfigPage />}
      {view === "lobby" && (
        <div className={styles.lobbyWrap}>
          <div className={styles.lobbyBrand}>
            <div className={styles.avatar}>
              <IconSparkles size={18} />
            </div>
            <span className={styles.wordmark}>Orchestrator</span>
          </div>
          <p className={styles.lobbyTag}>想清楚一件事，和能挑战你想法的助手一起。</p>
          {leaveSummary && (
            <div className={styles.leaveSummary} data-testid="leave-summary">
              <p>
                已离开房间。本次会话共 {leaveSummary.eventCountOnLeave} 条消息
                {leaveSummary.decisionCount > 0 && `，作出了 ${leaveSummary.decisionCount} 个决定`}
                。
              </p>
              <button
                className={styles.returnBtn}
                data-testid="return-room-btn"
                onClick={() => void handleReturn(leaveSummary.roomId)}
              >
                返回房间
              </button>
            </div>
          )}
          <div className={styles.lobby}>
            <RoomCreate />
            <div className={styles.divider}>或者</div>
            <RoomPicker />
          </div>
        </div>
      )}
    </div>
  );
}
