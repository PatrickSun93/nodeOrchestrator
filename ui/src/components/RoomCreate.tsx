import { useState } from "react";
import { createRoom } from "../api/client.ts";
import type { RoomType, IntentError } from "../api/client.ts";
import { useRoomStore } from "../store.ts";
import { roomTypeLabel } from "../uiStrings.ts";
import styles from "./RoomCreate.module.css";

const ROOM_TYPES: RoomType[] = [
  "free_chat",
  "bug_fix",
  "research",
  "code_review",
  "idea_validation",
];

export function RoomCreate() {
  const [roomType, setRoomType] = useState<RoomType>("free_chat");
  const [error, setError] = useState<string | null>(null);
  const setRoom = useRoomStore((s) => s.setRoom);

  async function handleCreate() {
    setError(null);
    try {
      const room = await createRoom(roomType);
      setRoom(room.id, room.type);
    } catch (err) {
      setError((err as IntentError).reason ?? "创建失败");
    }
  }

  return (
    <div className={styles.create} data-testid="room-create">
      <h2>新建房间</h2>
      <div className={styles.row}>
        <select
          value={roomType}
          onChange={(e) => setRoomType(e.target.value as RoomType)}
          className={styles.select}
          data-testid="room-type-select"
        >
          {ROOM_TYPES.map((t) => (
            <option key={t} value={t}>
              {roomTypeLabel(t)}
            </option>
          ))}
        </select>
        <button
          onClick={() => void handleCreate()}
          className={styles.btn}
          data-testid="create-button"
        >
          创建
        </button>
      </div>
      {error && (
        <div className={styles.error} data-testid="create-error">
          {error}
        </div>
      )}
    </div>
  );
}
