import { mount } from "svelte";
import App from "./App.svelte";
import "katex/dist/katex.min.css";
import "@tabler/icons-webfont/dist/tabler-icons.min.css";
import "./styles.css";

const app = mount(App, {
  target: document.getElementById("app")!,
});

export default app;
