/**
 * IMS Portal — Universal Floating AI Chatbot
 */

(function () {
  const CHAT_STORAGE_KEY = "ims_ai_chat_history";

  let chatHistory = [];
  let isThinking = false;

  // DOM Elements
  const launcher = document.getElementById("ims-chat-launcher");
  const widget = document.getElementById("ims-chat-widget");
  const closeBtn = document.getElementById("ims-chat-close-btn");
  const clearBtn = document.getElementById("ims-chat-clear-btn");
  const messagesContainer = document.getElementById("ims-chat-messages");
  const inputField = document.getElementById("ims-chat-input");
  const sendBtn = document.getElementById("ims-chat-send-btn");
  const suggestionsBox = document.getElementById("ims-chat-suggestions");

  if (!launcher || !widget) return;

  // User Role & Name
  const userRole = widget.getAttribute("data-role") || "trainee";
  const userName = widget.getAttribute("data-name") || "User";

  // Initial role suggestions
  const roleSuggestions = {
    trainee: [
      "How is my attendance & score?",
      "How to improve my performance?",
      "Explain my recent assignments",
      "Give me study tips for exams"
    ],
    mentor: [
      "Which students need urgent help?",
      "Summarize class performance",
      "Draft a class announcement",
      "Tips to increase student engagement"
    ],
    admin: [
      "Summarize platform statistics",
      "Analyze institutional risk",
      "Overview of student development",
      "System maintenance checklist"
    ]
  };

  // Simple Markdown Parser
  function formatMarkdown(text) {
    if (!text) return "";
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Code blocks
    html = html.replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
    // Inline code
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Italic
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    // Headings
    html = html.replace(/^### (.*$)/gim, "<h4 style='margin:6px 0;font-size:14px;color:#1e1b4b;'>$1</h4>");
    html = html.replace(/^## (.*$)/gim, "<h3 style='margin:8px 0;font-size:15px;color:#1e1b4b;'>$1</h3>");

    // Bullet points
    const lines = html.split("\n");
    let inList = false;
    let listHtml = "";

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        if (!inList) {
          listHtml += "<ul>";
          inList = true;
        }
        listHtml += `<li>${trimmed.substring(2)}</li>`;
      } else if (/^\d+\.\s/.test(trimmed)) {
        if (!inList) {
          listHtml += "<ol>";
          inList = true;
        }
        listHtml += `<li>${trimmed.replace(/^\d+\.\s/, "")}</li>`;
      } else {
        if (inList) {
          listHtml += inList === "ol" ? "</ol>" : "</ul>";
          inList = false;
        }
        if (trimmed) {
          listHtml += `<p>${line}</p>`;
        }
      }
    });

    if (inList) {
      listHtml += "</ul>";
    }

    return listHtml || html;
  }

  // Load Saved History
  function loadHistory() {
    try {
      const saved = sessionStorage.getItem(CHAT_STORAGE_KEY);
      if (saved) {
        chatHistory = JSON.parse(saved);
        renderMessages();
      } else {
        // Welcome message
        addBotMessage(
          `Hello **${userName}**! 👋 I am your **IMS AI Smart Assistant**.\n\nI can help you navigate your ${userRole} dashboard, review performance insights, answer academic questions, or assist with any IMS tasks. How can I help you today?`
        );
      }
    } catch (e) {
      console.warn("Could not load chat history", e);
    }
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(chatHistory));
    } catch (e) {}
  }

  // Render All Messages
  function renderMessages() {
    messagesContainer.innerHTML = "";
    chatHistory.forEach((msg) => {
      appendMessageToDOM(msg.sender, msg.text, msg.time);
    });
    scrollToBottom();
  }

  function appendMessageToDOM(sender, text, time) {
    const isUser = sender === "user";
    const msgDiv = document.createElement("div");
    msgDiv.className = `ims-chat-msg ${isUser ? "user" : "bot"}`;

    const formattedContent = isUser
      ? `<p>${text.replace(/\n/g, "<br>")}</p>`
      : formatMarkdown(text);

    msgDiv.innerHTML = `
      <div class="ims-msg-bubble">
        ${formattedContent}
        <div class="ims-msg-time">${time || ""}</div>
      </div>
    `;

    messagesContainer.appendChild(msgDiv);
    scrollToBottom();
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function getTimeString() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function addUserMessage(text) {
    const time = getTimeString();
    chatHistory.push({ sender: "user", text: text, time: time });
    appendMessageToDOM("user", text, time);
    saveHistory();
  }

  function addBotMessage(text) {
    const time = getTimeString();
    chatHistory.push({ sender: "bot", text: text, time: time });
    appendMessageToDOM("bot", text, time);
    saveHistory();
  }

  function showTypingIndicator() {
    const indicator = document.createElement("div");
    indicator.id = "ims-typing-indicator";
    indicator.className = "ims-chat-msg bot";
    indicator.innerHTML = `
      <div class="ims-typing-indicator">
        <div class="ims-typing-dot"></div>
        <div class="ims-typing-dot"></div>
        <div class="ims-typing-dot"></div>
      </div>
    `;
    messagesContainer.appendChild(indicator);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    const indicator = document.getElementById("ims-typing-indicator");
    if (indicator) indicator.remove();
  }

  // Populate Suggestions
  function renderSuggestions() {
    if (!suggestionsBox) return;
    suggestionsBox.innerHTML = "";
    const suggestions = roleSuggestions[userRole] || roleSuggestions.trainee;
    suggestions.forEach((prompt) => {
      const chip = document.createElement("button");
      chip.className = "ims-chip-btn";
      chip.textContent = prompt;
      chip.onclick = () => {
        inputField.value = prompt;
        sendMessage();
      };
      suggestionsBox.appendChild(chip);
    });
  }

  // Send Message Logic
  async function sendMessage() {
    const text = inputField.value.trim();
    if (!text || isThinking) return;

    inputField.value = "";
    addUserMessage(text);

    isThinking = true;
    sendBtn.disabled = true;
    showTypingIndicator();

    // Prepare conversation turns for context
    const conversationTurns = [];
    for (let i = 0; i < chatHistory.length; i++) {
      if (chatHistory[i].sender === "user") {
        conversationTurns.push({
          user: chatHistory[i].text,
          bot: chatHistory[i + 1]?.sender === "bot" ? chatHistory[i + 1].text : ""
        });
      }
    }

    try {
      const response = await fetch("/api/ai/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          message: text,
          history: conversationTurns
        })
      });

      const data = await response.json();
      removeTypingIndicator();

      if (data.success && data.reply) {
        addBotMessage(data.reply);
      } else {
        addBotMessage(
          "I apologize, but I encountered an issue processing your request. Please try again in a moment."
        );
      }
    } catch (error) {
      removeTypingIndicator();
      console.error("Chatbot API error:", error);
      addBotMessage(
        "Network connection issue. Please check your connection and try again."
      );
    } finally {
      isThinking = false;
      sendBtn.disabled = false;
      inputField.focus();
    }
  }

  // Toggle Visibility
  function toggleWidget() {
    const isOpen = widget.classList.contains("active");
    if (isOpen) {
      widget.classList.remove("active");
      launcher.style.transform = "";
    } else {
      widget.classList.add("active");
      launcher.style.transform = "scale(0.9)";
      inputField.focus();
      scrollToBottom();
    }
  }

  // Event Listeners
  launcher.addEventListener("click", toggleWidget);
  closeBtn.addEventListener("click", toggleWidget);

  clearBtn.addEventListener("click", () => {
    if (confirm("Clear conversation history?")) {
      chatHistory = [];
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
      addBotMessage(
        `Conversation cleared! How can I assist you now, **${userName}**?`
      );
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  inputField.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Initialize
  renderSuggestions();
  loadHistory();
})();
