import type { Event } from "../api/client.ts";
import { authorLabel, eventTypeLabel } from "../uiStrings.ts";
import styles from "./MessageItem.module.css";

interface Props {
  event: Event;
}

export function MessageItem({ event }: Props) {
  const author = authorLabel(event.author);
  const typeChip = eventTypeLabel(event.type);
  const isUser = event.author === "user";

  return (
    <div
      className={`${styles.item} ${isUser ? styles.user : styles.agent}`}
      data-testid="message-item"
    >
      <div className={styles.header}>
        <span className={styles.author}>{author}</span>
        <span className={styles.chip}>{typeChip}</span>
      </div>
      <div className={styles.content}>{event.content}</div>
    </div>
  );
}
