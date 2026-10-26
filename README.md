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

## New (Oct 26, 2026)

- **Status strip:** CPU/GPU temps, memory, last backup, backup drive, internet, local AIs. Goes red only when
  something's actually wrong. Refreshes every 30 seconds.
- **PC buttons:** a short fixed list: back up now, put the local AIs to sleep (free the GPU memory), lock the PC,
  and say something out loud on the PC speakers. Nothing else can be run from the iPad.
- **The away team:** three Claude Code agents (a planner, a Linux tutor, a notes keeper) you can chat with from
  the iPad. **Talk-only:** default permissions plus a tool lock (no shell, no file edits, no web, no MCP tools).
  They use agents from your own `~/.claude/agents`, so bring your own or delete those cards.
- **Keeps the PC awake** while you're using the Guide: each use renews a 30-minute suspend inhibitor, so GNOME's
  idle sleep doesn't pull the plug mid-chat. The screen can still lock.
- **Security pass:** your chat text goes to Claude on stdin, never in the command line (so a message starting
  with `--` can't become an option); request size and JSON checks; Content-Security-Policy and no-referrer
  headers; constant-time key checks; one spoken message at a time; at most two Claude chats at once.

**Private by design:** one stdlib Python file on port 4200. It only answers this PC and Tailscale devices
(100.64.0.0/10), and only with a random key. Open `http://<your-pc-tailscale-ip>:4200/?key=<key>` once, then
Share → Add to Home Screen. Sized for an 11" iPad (1180×820), works on phones too.

## License

MIT. Built by Rabbid Raccoon with Claude. Use it, change it, share it.
