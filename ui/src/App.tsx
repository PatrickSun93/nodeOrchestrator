import { useRoomStore } from "./store.ts";
import { RoomPicker } from "./components/RoomPicker.tsx";
import { RoomCreate } from "./components/RoomCreate.tsx";
import { RoomView } from "./components/RoomView.tsx";
import styles from "./App.module.css";

export default function App() {
  const roomId = useRoomStore((s) => s.roomId);

  if (roomId) {
    return (
      <div className={styles.app}>
        <RoomView />
      </div>
    );
  }

  return (
    <div className={styles.app}>
      <h1 className={styles.title}>Orchestrator</h1>
      <div className={styles.lobby}>
        <RoomCreate />
        <div className={styles.divider}>— 或者 —</div>
        <RoomPicker />
      </div>
    </div>
  );
}
