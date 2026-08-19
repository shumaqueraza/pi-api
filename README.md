# 🥧 Pi API — what if pi.ai had an API

> *"If the browser can do it, the browser has to know how."*

So here's the thing. **Pi doesn't give you an API key.** It just doesn't exist. But the website works, right? You go to pi.ai, you talk to Pi, it responds. 

The browser is literally making **HTTP requests to somewhere.** It has to be.

So I went looking.

This is what I found.

---

## 🤖 What's Pi.ai anyway

[Pi](https://pi.ai) is made by [**Inflection AI**](https://www.inflection.ai/). It's not trying to be ChatGPT or Claude or any of the *"here's a model endpoint"* things.

It's designed to **actually talk to you.** Like a real conversation. No model selector, no system prompt visible, no *"answer format"*. Just you and Pi having a dialogue.

The vibe is closer to **texting a thoughtful friend** than using an API. Pi actually remembers context, asks follow-up questions, picks up on tone. It's weirdly natural.

The catch? **It's only on their website.** You can't integrate it anywhere. You can't use it in your own app. You just go to pi.ai and that's it.

Which is fine for some people. But if you wanted to *use* Pi somewhere else, you were out of luck.

Until now.

---

## 🌉 Ok but what actually is this

**Pi API is a reverse-engineered gateway to pi.ai**

So we have Pi, which only works on their website. And we have this project, which makes Pi **work like a normal API.**

But underneath that simple interface? **The browser is doing a lot of work.**

- 💬 Creating conversations
- 📤 Sending messages
- 📥 Getting streamed responses back
- 🧭 Keeping track of where you are
- 🔐 Managing authentication
- ☁️ Dealing with Cloudflare

All of that is happening in **network requests.** Requests that the website *has to know about* because otherwise it wouldn't work.

This project figured out what those requests look like and built a **local API bridge** that lets you talk to Pi like it actually had an official interface.

```
your client (OpenAI SDK, custom app, whatever)
                    ↓
            Pi API (local)
                    ↓
         pi.ai (actual AI)
```

You get all the normal OpenAI-compatible stuff. **Pi does the thinking.** Done.

---

## 🔍 Why tho

Because the *interesting* question isn't *"can I use Pi?"*

The interesting question is **"how does the website use Pi?"**

There's no documentation for this. There's just... the website working. The browser making requests. The whole thing talking to itself.

So the rabbit hole was:

- 🔎 How does Pi **create conversations?** What's the request?
- 💬 How do you **send messages?** What payload shape does it expect?
- 🌊 How does **streaming work?** What format are the events?
- 🍪 **Which cookies actually matter?** (spoiler: like 3)
- ☁️ How do you **keep Cloudflare happy?**
- 🧠 How does Pi **know which conversation** you're in?
- 🪪 **What headers** does the browser send that actually matter?

The website already had all these answers. They just weren't written down anywhere. So I watched the network tab and figured it out.

---

## 🏗️ The architecture (tldr)

Two endpoints matter:

```
https://pi.ai/api/conversations     (create a new conversation)
https://pi.ai/api/v2/chat           (send a message, get streamed response)
```

That's it. Everything else is just:

- **Making those requests look like they came from a browser** (curl_cffi does this with Chrome impersonation)
- **Managing your Pi session cookies**
- **Keeping Cloudflare happy**
- **Handling the streaming events**
- **Wrapping it in an OpenAI-compatible API**

---

## 💡 The conversation hack (my favorite part)

Normally with an API, you send your **entire conversation history** every single time:

```
user: hey
assistant: hey what's up?
user: what were we talking about?
```

But Pi already *has* the conversation. **Why rebuild it every request?**

So instead: when Pi creates a conversation, I just... **save the ID.** Stick it on the assistant's response as a hidden marker:

```
assistant response text here
[pi-conv:ABC123]
```

Next time the client sends a message, the API **looks for that marker** in the conversation history, finds the ID, and **reuses that conversation** on Pi's end.

The client never has to know about it. **It just works.**

```
Request 1:
  create Pi conversation → get ABC123
  send message
  response: "..." + [pi-conv:ABC123]

Request 2:
  find [pi-conv:ABC123] in history
  reuse that conversation
  send new message to ABC123
  response: "..." + [pi-conv:ABC123]
```

**No database needed.** Just one tiny marker. That's it.

---

## ✨ What you actually get

| | |
| --- | --- |
| 💬 | **OpenAI-compatible** chat completions (plug in your existing SDK) |
| 🌊 | **Streaming responses** (get tokens as they arrive) |
| 🧠 | **Conversation continuity** (Pi remembers the thread) |
| 🍪 | **Browser session auth** (uses your Pi cookies) |
| ☁️ | **Cloudflare babysitting** (keeps the session alive) |
| 🌐 | **CORS support** (works from browser too) |
| 🔐 | **Optional local API key** (if you want to lock it down) |
| 🖥️ | **Readable logging** (actually tells you what's happening) |

---

## ⚠️ Use a burner account

**Seriously, use a separate Pi account for this.**

This project is reverse engineering a web service that was not designed to be consumed through this interface. Your `cookies.json` contains **authentication material for your Pi session.**

If the account matters to you, don't use it here. **Use a burner / alt account instead.**

- 🔐 **Don't use your main Pi account**
- 🍪 **Never share `cookies.json`**
- 🚫 **Never commit `cookies.json` to git**
- 🌐 **Don't expose your authenticated server publicly**
- 🧪 **Treat the account as disposable**

> **If losing the account would ruin your day, don't use that account here.**

You're handing a local program the same session information your browser uses to access Pi. Keep that boundary very clear.

---

## 🚀 Getting started

### 📋 You need:

- **Python 3.9+**
- **A Pi.ai account** (use a burner)
- **[Cookie-Editor](https://cookie-editor.com/)** (or any cookie exporter)
- **30 seconds** to export your cookies

### 1️⃣ Clone this

```bash
git clone https://github.com/shumaqueraza/pi-api.git
cd pi-api
```

### 2️⃣ Install deps

```bash
pip install -r requirements.txt
```

### 3️⃣ Get your cookies

1. Go to [pi.ai](https://pi.ai) and **log in** (on your burner account)
2. Install [**Cookie-Editor**](https://cookie-editor.com/)
3. Click the extension → **export** → copy the JSON
4. Save it as **`cookies.json`** in the pi-api folder

Folder should look like:

```
pi-api/
├── pi-api.py
├── cookies.json         ← here
├── requirements.txt
└── README.md
```

### 4️⃣ Start the server

```bash
python pi-api.py
```

You'll see a fancy startup panel with all the settings. Server runs on **`http://127.0.0.1:8000`**

---

## 💻 Using it

Once it's running, if you know the **OpenAI Python SDK** you already know how to use this:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="anything"  # doesn't matter if you didn't set one
)

response = client.chat.completions.create(
    model="pi",
    messages=[
        {"role": "user", "content": "tell me something cool"}
    ]
)

print(response.choices[0].message.content)
```

### 🌊 Streaming

```python
stream = client.chat.completions.create(
    model="pi",
    messages=[
        {"role": "user", "content": "tell me a story"}
    ],
    stream=True
)

for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

### 🔌 In other apps

If some app lets you configure an **OpenAI-compatible endpoint:**

```
Base URL: http://127.0.0.1:8000/v1
Model: pi
```

That's literally all you need.

---

## 📡 API endpoints

### `POST /v1/chat/completions`

**The main endpoint.** Send this:

```json
{
  "model": "pi",
  "messages": [
    {
      "role": "user",
      "content": "hello"
    }
  ]
}
```

Or with **streaming:**

```json
{
  "model": "pi",
  "stream": true,
  "messages": [
    {
      "role": "user",
      "content": "tell me something"
    }
  ]
}
```

Response is **standard OpenAI format.**

### `GET /v1/models`

```json
{
  "object": "list",
  "data": [
    {
      "id": "pi",
      "object": "model",
      "created": 0,
      "owned_by": "inflection"
    }
  ]
}
```

### `GET /health`

```json
{
  "status": "ok",
  "cookies": 3
}
```

---

## ⚙️ Configuration

**Top of `pi-api.py`:**

```python
PORT = 8000
HOST = "127.0.0.1"
SHIM_API_KEY = ""
COOKIES_FILE = "cookies.json"
CF_REFRESH_SECS = 25 * 60
```

### 🏠 `HOST`

**Default:** `127.0.0.1` (keeps it local)

If you change it to `0.0.0.0` it'll be accessible over your network.

**Don't do this unless you know what you're doing.** This server has your Pi session. **Treat it like your browser.**

### 🚪 `PORT`

Wherever you want it. Default is **8000.**

### 🔑 `SHIM_API_KEY`

**Empty by default** (no auth needed).

If you set it:

```python
SHIM_API_KEY = "super-secret-thing"
```

**Clients have to send:**

```
Authorization: Bearer super-secret-thing
```

### 🍪 `COOKIES_FILE`

Path to your cookies JSON.

### ⏰ `CF_REFRESH_SECS`

How often to poke Cloudflare. **Default is fine.**

### 📏 `Prompt cap`

**Hardcoded at 4000 chars.** This is a **Pi.ai limit**, not an arbitrary choice. Pi itself rejects anything longer, so there's no point changing it.

---

## 📦 What's in the box

It's mostly just **one file** (`pi-api.py`) with:

| Part | Job |
| --- | --- |
| `CookieManager` | **Loads your Pi cookies, keeps them fresh** |
| `PiClient` | **Talks to Pi's endpoints** |
| Conversation handling | **Finds and reuses Pi conversation IDs** |
| SSE parser | **Reads Pi's stream format** |
| FastAPI app | **Exposes the OpenAI endpoint** |
| Rich logging | **Makes terminal output actually readable** |

**Dependencies are intentionally tiny:**

```
curl_cffi        (for browser impersonation)
fastapi          (for the API)
uvicorn          (for the server)
pydantic         (for data validation)
rich             (for the pretty terminal)
```

**No database. No frontend. No bloat.** Just the bridge.

---

## 💥 Things that can break

This is the **"you get what you get" part** of reverse engineering.

Pi can change:

- Their endpoints
- Their request format
- Their headers
- How Cloudflare works
- Their streaming format
- **Literally anything**

If that happens, **the API breaks.** That's just how it is.

**If you see 401 / 403 / 502:**

1. Export fresh cookies
2. Try again

**If that doesn't work:**

**Pi probably changed something.** Which is when the fun part starts. Open DevTools, watch the network tab, figure out what changed, update the code.

That's the whole game.

---

## 🖥️ Logging

**The terminal is your UI.** So instead of:

```
INFO: something happened
INFO: something else
ERROR: failure
```

You get **actual information** that's readable at a glance:

```
✓ conversation created
→ reuse conversation (prompt=...)
⚠ prompt too long
✗ auth rejected
```

**Startup info gets its own panel.** Errors get their own panel. Things that work are green. Things that might be problems are yellow. Things that broke are red.

**Glance at it and you know what's happening.**

---

## ✌️ Not affiliated, not official, all vibes

This is a **reverse engineering project.** Made because the website already does the thing but didn't document how.

**This is not:**
- An official Inflection product
- An official Pi.ai library
- Affiliated with Inflection in any way
- A hosted service
- A replacement for pi.ai

**This is:**
- A local bridge that talks to Pi the same way your browser does
- Something you run on your own machine
- A way to use Pi if you already have a session
- Fun

---

## ⚖️ Legal stuff

**Inflection doesn't endorse this.** Pi.ai doesn't have an official API because Inflection chose not to make one. This project reverse engineers the web interface.

So like. **Keep it local.** Use a burner account. Don't be weird with it. **Review Inflection's terms** if you're doing anything beyond just messing around.

---

## ⚠️ Disclaimer

**Pi API is unofficial.** It's not made by Inflection. It talks to Pi using your browser session (the same cookies your browser uses).

That means:
- **It could stop working** anytime Pi changes something
- **Pi could disable your account** if they don't like it
- **Your cookies have your session auth** in them (treat them like passwords)
- **You're responsible** for what you do with this
- **Use a burner account**

---

## 📜 License

**MIT**

---

> *The website was never supposed to be the API documentation. Turns out it was all along.*