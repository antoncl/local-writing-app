import { mount } from "svelte";
import App from "./App.svelte";
import { startSessionPresence } from "./lib/sessionPresence";
import "./lib/icons/generated/tabler-subset.css";
import "./styles.css";

const app = mount(App, {
  target: document.getElementById("app")!,
});

// Let a desktop launch quit when this tab closes (#1378). Harmless everywhere
// else: a LAN/systemd server just holds an unused socket.
startSessionPresence();

export default app;
