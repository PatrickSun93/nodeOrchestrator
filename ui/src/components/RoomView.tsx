import { useRoomStore } from "../store.ts";
import { useRoomStream } from "../hooks/useRoomStream.ts";
import { MessageList } from "./MessageList.tsx";
import { Composer } from "./Composer.tsx";
import { ConnectionStatus } from "./ConnectionStatus.tsx";
import { PendingDecisionList } from "./PendingDecision.tsx";
import { roomStateLabel, roomTypeLabel } from "../uiStrings.ts";
import styles from "./RoomView.module.css";

export function RoomView() {
  const roomId = useRoomStore((s) => s.roomId);
  const roomType = useRoomStore((s) => s.roomType);
  const events = useRoomStore((s) => s.events);
  const phase = useRoomStore((s) => s.phase);

  useRoomStream(roomId);

  if (!roomId) return null;

  return (
    <div className={styles.view} data-testid="room-view">
      <header className={styles.header}>
        <span className={styles.roomId}>{roomId}</span>
        {roomType && <span className={styles.roomType}>{roomTypeLabel(roomType)}</span>}
        <ConnectionStatus phase={phase} />
      </header>
      <MessageList events={events} />
      <PendingDecisionList />
      <Composer />
    </div>
  );
}

export function RoomViewWithState({ roomState }: { roomState?: string }) {
  if (!roomState) return null;
  return <span data-testid="room-state-label">{roomStateLabel(roomState)}</span>;
}
