import { mount } from "svelte";
import App from "./App.svelte";
import "katex/dist/katex.min.css";
import "./lib/icons/generated/tabler-subset.css";
import "./styles.css";

const app = mount(App, {
  target: document.getElementById("app")!,
});

export default app;
