import { useEffect, useState } from "react";
import { listRooms } from "../api/client.ts";
import type { Room } from "../api/client.ts";
import { useRoomStore } from "../store.ts";
import { roomTypeLabel, roomStateLabel } from "../uiStrings.ts";
import styles from "./RoomList.module.css";

export function RoomList() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const setRoom = useRoomStore((s) => s.setRoom);

  useEffect(() => {
    listRooms()
      .then(setRooms)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return null;

  return (
    <div className={styles.list} data-testid="room-list">
      <h2>现有房间</h2>
      {rooms.length === 0 ? (
        <p className={styles.empty} data-testid="room-list-empty">
          暂无房间，请先创建一个。
        </p>
      ) : (
        <ul className={styles.items}>
          {rooms.map((room) => (
            <li key={room.id}>
              <button
                className={styles.item}
                data-testid={`room-item-${room.id}`}
                onClick={() => setRoom(room.id, room.type)}
              >
                <span className={styles.type}>{roomTypeLabel(room.type)}</span>
                <span className={styles.state}>{roomStateLabel(room.state)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
