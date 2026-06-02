import type { Event } from "../api/client.ts";
import { MessageItem } from "./MessageItem.tsx";
import styles from "./MessageList.module.css";

interface Props {
  events: Event[];
}

export function MessageList({ events }: Props) {
  return (
    <div className={styles.list} data-testid="message-list">
      {events.map((evt) => (
        <MessageItem key={evt.id} event={evt} />
      ))}
    </div>
  );
}
