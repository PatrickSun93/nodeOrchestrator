import { useState } from "react";
import { getRoom } from "../api/client.ts";
import type { IntentError } from "../api/client.ts";
import { useRoomStore } from "../store.ts";
import styles from "./RoomPicker.module.css";

export function RoomPicker() {
  const [roomId, setRoomId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const setRoom = useRoomStore((s) => s.setRoom);

  async function handleJoin() {
    const id = roomId.trim();
    if (!id) return;
    setError(null);
    try {
      const room = await getRoom(id);
      setRoom(room.id, room.type);
    } catch (err) {
      setError((err as IntentError).reason ?? "无法找到房间");
    }
  }

  return (
    <div className={styles.picker} data-testid="room-picker">
      <h2>加入已有房间</h2>
      <div className={styles.row}>
        <input
          type="text"
          value={roomId}
          onChange={(e) => setRoomId(e.target.value)}
          placeholder="房间 ID"
          className={styles.input}
          data-testid="room-id-input"
        />
        <button onClick={() => void handleJoin()} className={styles.btn} data-testid="join-button">
          加入
        </button>
      </div>
      {error && (
        <div className={styles.error} data-testid="picker-error">
          {error}
        </div>
      )}
    </div>
  );
}
