# The Hitchhiker's Guide 🦝 DON'T PANIC

An iPad home-screen app that talks to AIs running on your own PC. Tap the big friendly DON'T PANIC icon,
pick a character, chat. The PC does all the work; the iPad is just the window.

| Character | Brain |
|---|---|
| Deep Thought | Claude (`claude -p`, keeps one conversation going) |
| Eddie | free cloud AI, everyday chat |
| Trillian | free cloud AI, thinks hard |
| Slartibartfast | free cloud AI, the builder (Linux, code, how-to) |
| Marvin | local Ollama model on your GPU, works with no internet |
| Ford Prefect | small local Ollama model, quick, works offline |

The free cloud characters go through a LiteLLM "brain switch" (see the `crew` repo); local ones call Ollama
directly and start it on demand. Chats are saved on the PC, so your iPad and phone see the same conversations.
There's also a row of buttons for the AI apps already on the iPad.

**Private by design:** one stdlib Python file on port 4200. It only answers this PC and Tailscale devices
(100.64.0.0/10), and only with a random key. Open `http://<your-tailscale-ip>:4200/?key=<key>` once, then
Share → Add to Home Screen. Sized for an 11" iPad (1180×820), works on phones too.

## License

MIT. Built by Rabbid Raccoon with Claude. Use it, change it, share it.
