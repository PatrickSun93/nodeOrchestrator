import { useState, useCallback } from "react";
import { IconSparkles } from "@tabler/icons-react";
import { useRoomStore } from "./store.ts";
import { getEvents, getSnapshot } from "./api/client.ts";
import { RoomPicker } from "./components/RoomPicker.tsx";
import { RoomCreate } from "./components/RoomCreate.tsx";
import { RoomView } from "./components/RoomView.tsx";
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

  const handleLeave = useCallback(async () => {
    if (!roomId) return;
    // Fetch snapshot to generate leave summary
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
      // Reload events to calculate catch-up count
      const setRoom = useRoomStore.getState().setRoom;
      try {
        const [events, room] = await Promise.all([
          getEvents(returnRoomId),
          getSnapshot(returnRoomId),
        ]);
        const newEvents = events.length - leaveSummary.eventCountOnLeave;
        setRoom(returnRoomId, room.room_type as Parameters<typeof setRoom>[1]);
        if (newEvents > 0) {
          // Catch-up notice (pattern 5 return)
          alert(`离开后有 ${newEvents} 条新消息`);
        }
      } catch {
        const roomData = await import("./api/client.ts").then((m) => m.getRoom(returnRoomId));
        setRoom(returnRoomId, roomData.type);
      }
      setLeaveSummary(null);
    },
    [leaveSummary],
  );

  if (roomId) {
    return (
      <div className={styles.app}>
        <RoomView onLeave={() => void handleLeave()} />
      </div>
    );
  }

  return (
    <div className={styles.app}>
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
              {leaveSummary.decisionCount > 0 && `，作出了 ${leaveSummary.decisionCount} 个决定`}。
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
    </div>
  );
}
