# 📊 System Architecture Diagrams

This document visually explains the architecture, data flow, and core workflows of the **AI News Ecosystem** project.

---

## 1. High-Level Architecture

This diagram outlines how the Frontend (Next.js), Backend (FastAPI), Database (SQLite), AI Services (Gemini), and Event Queue (Kafka) communicate with each other.

![High-Level Architecture](./images/architecture.png)

---

## 2. News Ingestion Pipeline

This diagram explains how raw news articles are sourced, deduplicated, and stored in the database every 6 hours.

![News Ingestion Pipeline](./images/ingestion.png)

---

## 3. AI Summarization Flow (Kid vs. Pro Mode)

This diagram illustrates what happens when a user clicks on an article and requests a summary. It highlights how the backend decides whether to fetch an existing summary from the DB or dynamically generate one using Google Gemini.

![AI Summarization Flow](./images/summarization.png)

---

## 4. Gamification & Quiz Flow

This diagram maps out how points are awarded for reading time and how the weekly quizzes are dynamically generated based on the latest news articles in the database.

```mermaid
graph TD
    subgraph Reading Points Flow
        A[User Opens Article] --> B[30-Second Timer Starts]
        B --> C{Stayed > 30 seconds?}
        C -->|No| D[No Points Awarded]
        C -->|Yes| E["POST /user/reading-time"]
        E --> F[(Database)]
        F --> G[Award 10 Points]
    end

    subgraph Quiz Generation Flow
        H[User Opens Quiz Page] --> I{Weekly Quiz Exists?}
        I -->|Yes| J[Load Existing Quiz]
        I -->|No| K[Fetch 5 Recent Articles]
        K --> L["Send to Gemini AI"]
        L --> M[Generate 10 MCQ Questions]
        M --> N[(Save Quiz to Database)]
        N --> O[Return Quiz to User]
    end
```
