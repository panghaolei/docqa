<template>
  <!-- 登录页 -->
  <div class="login-wrap" v-if="!logged">
    <div class="login-card">
      <div class="login-logo">
        <el-icon :size="36"><ChatDotRound /></el-icon>
      </div>
      <h2 class="login-title">智能文档问答</h2>
      <p class="login-subtitle">基于 RAG · DeepSeek + BGE 向量检索</p>
      <el-input
        v-model="username"
        placeholder="请输入用户名"
        size="large"
        @keyup.enter="doLogin"
        :prefix-icon="User"
      />
      <el-button
        type="primary"
        size="large"
        class="login-btn"
        :loading="logining"
        @click="doLogin"
      >
        {{ logining ? '登录中...' : '进入系统' }}
      </el-button>
      <p class="login-tip">首次输入用户名将自动注册</p>
    </div>
  </div>

  <!-- 主界面 -->
  <div v-else class="app-layout">
    <!-- 左侧深色 Sidebar -->
    <aside class="sidebar">
      <!-- 顶部 Logo -->
      <div class="sidebar-brand">
        <div class="brand-icon">
          <el-icon :size="20"><ChatDotRound /></el-icon>
        </div>
        <div class="brand-text">
          <div class="brand-title">智能文档问答</div>
          <div class="brand-sub">RAG · DeepSeek</div>
        </div>
      </div>

      <!-- 新建对话按钮 -->
      <div class="sidebar-new">
        <el-button class="new-chat-btn" :icon="Plus" @click="newChat">
          <span>新建对话</span>
        </el-button>
      </div>

      <!-- 滚动区域 -->
      <div class="sidebar-scroll">
        <!-- 会话列表 -->
        <div class="sidebar-section">
          <div class="section-header">
            <el-icon><ChatLineRound /></el-icon>
            <span>对话历史</span>
            <span class="section-count">{{ sessions.length }}</span>
          </div>
          <div class="session-list">
            <div
              v-for="s in sessions"
              :key="s.id"
              :class="['session-item', { active: s.id === currentSessionId }]"
              @click="selectSession(s.id)"
            >
              <el-icon class="session-icon"><Message /></el-icon>
              <span class="session-title">{{ s.title || '新对话' }}</span>
              <el-icon class="session-del" @click.stop="removeSession(s.id)"><Close /></el-icon>
            </div>
            <div v-if="!sessions.length" class="empty-hint">
              <el-icon><DocumentAdd /></el-icon>
              <span>点击"新建对话"开始</span>
            </div>
          </div>
        </div>

        <!-- 文档管理 -->
        <div class="sidebar-section">
          <div class="section-header">
            <el-icon><Folder /></el-icon>
            <span>知识库文档</span>
            <span class="section-count">{{ documents.length }}</span>
          </div>

          <el-upload
            :show-file-list="false"
            :http-request="customUpload"
            accept=".pdf,.doc,.docx,.txt,.md,.html"
            class="upload-trigger"
          >
            <div class="upload-btn">
              <el-icon><UploadFilled /></el-icon>
              <span>{{ uploading ? '上传中...' : '点击或拖拽上传' }}</span>
            </div>
          </el-upload>

          <div class="doc-list">
            <div v-for="d in documents" :key="d.id" class="doc-item">
              <el-icon class="doc-icon"><Document /></el-icon>
              <div class="doc-meta">
                <div class="doc-name" :title="d.fileName">{{ d.fileName }}</div>
                <div class="doc-status">
                  <span :class="['status-dot', `status-${(d.status || '').toLowerCase()}`]"></span>
                  <span>{{ statusText(d.status) }}</span>
                </div>
              </div>
              <el-icon class="doc-del" @click="removeDoc(d.id)"><Delete /></el-icon>
            </div>
            <div v-if="!documents.length" class="empty-hint small">
              <span>暂无文档</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部用户栏 -->
      <div class="sidebar-footer">
        <div class="user-card">
          <div class="user-avatar">
            <el-icon :size="16"><User /></el-icon>
          </div>
          <div class="user-info">
            <div class="user-name">{{ username }}</div>
            <div class="user-action" @click="logout">退出登录</div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧主区 -->
    <main class="main-area">
      <!-- 顶部导航栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <span class="topbar-title">{{ currentTitle || '智能文档问答' }}</span>
          <el-tag size="small" type="info" effect="plain" class="topbar-tag">
            <el-icon><MagicStick /></el-icon>
            <span>基于 RAG</span>
          </el-tag>
        </div>
        <div class="topbar-right">
          <div class="topbar-icon" title="已上传文档">
            <el-icon :size="16"><Document /></el-icon>
            <span>{{ documents.length }}</span>
          </div>
          <div class="topbar-icon" title="对话数">
            <el-icon :size="16"><ChatDotRound /></el-icon>
            <span>{{ sessions.length }}</span>
          </div>
        </div>
      </header>

      <!-- 聊天区域 -->
      <div class="chat-container">
        <div class="messages" ref="msgBox">
          <!-- 欢迎界面 -->
          <div v-if="!messages.length" class="welcome">
            <div class="welcome-logo">
              <el-icon :size="48"><ChatDotRound /></el-icon>
            </div>
            <h1 class="welcome-title">开始你的智能问答</h1>
            <p class="welcome-desc">上传文档后，基于文档内容进行 RAG 检索增强回答</p>
            <div class="welcome-cards">
              <div class="welcome-card" @click="newChat">
                <el-icon :size="24"><Plus /></el-icon>
                <div class="card-title">新建对话</div>
                <div class="card-desc">开启新的问答</div>
              </div>
              <div class="welcome-card" @click="$refs.fileInput && $refs.fileInput.$el.querySelector('input').click()">
                <el-icon :size="24"><Upload /></el-icon>
                <div class="card-title">上传文档</div>
                <div class="card-desc">扩充知识库</div>
              </div>
              <div class="welcome-card" v-if="documents.length" @click="askDemo('这个文档的主要内容是什么？')">
                <el-icon :size="24"><Reading /></el-icon>
                <div class="card-title">快速提问</div>
                <div class="card-desc">基于已上传文档</div>
              </div>
            </div>
          </div>

          <!-- 消息列表 -->
          <div
            v-for="m in messages"
            :key="m.id || m._tmp"
            :class="['msg-row', m.role.toLowerCase()]"
          >
            <div class="msg-avatar">
              <el-icon v-if="m.role === 'USER'" :size="18"><User /></el-icon>
              <el-icon v-else :size="18"><Cpu /></el-icon>
            </div>
            <div class="msg-body">
              <div class="msg-meta">
                <span class="msg-author">{{ m.role === 'USER' ? username || '我' : 'AI 助手' }}</span>
              </div>
              <div class="msg-bubble markdown-body" v-html="renderMd(m.content)"></div>
              <div v-if="m.role === 'ASSISTANT' && m.refs" class="msg-refs">
                <el-icon :size="13"><Collection /></el-icon>
                <span class="refs-label">引用来源：</span>
                <span class="refs-docs">{{ m.refs }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-wrap">
        <div class="input-card">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            :placeholder="inputPlaceholder"
            @keydown.enter.exact.prevent="send"
            :disabled="inputDisabled"
            class="chat-input"
          />
          <el-button
            type="primary"
            class="send-btn"
            :icon="streaming ? '' : Promotion"
            :loading="streaming"
            @click="send"
            :disabled="!input.trim() || inputDisabled"
          >
            {{ streaming ? '思考中' : '发送' }}
          </el-button>
        </div>
        <div class="input-hint">
          <template v-if="!hasReadyDoc">请先上传并等待文档解析完成，再进行提问</template>
          <template v-else>AI 生成内容仅供参考 · 基于已上传文档进行 RAG 检索</template>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Upload, UploadFilled, Delete, Document, User, Cpu, Promotion,
  ChatDotRound, ChatLineRound, Message, Close, Folder, MagicStick,
  DocumentAdd, Reading, Collection
} from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  login, getToken, setToken, clearToken,
  uploadDocument, listDocuments, deleteDocument,
  listSessions, createSession, listMessages, deleteSession
} from './api'
import { streamChat } from './sse'

marked.setOptions({ breaks: true, gfm: true })

const logged = ref(!!getToken())
const username = ref('')
const logining = ref(false)

const sessions = ref([])
const currentSessionId = ref(null)
const currentTitle = ref('')
const messages = ref([])

const documents = ref([])
const uploading = ref(false)

const input = ref('')
const streaming = ref(false)
const msgBox = ref(null)

/* ---------- 文档状态感知 ---------- */
const hasAnyDoc = computed(() => documents.value.length > 0)
const hasReadyDoc = computed(() => documents.value.some(d => d.status === 'DONE'))
const hasProcessingDoc = computed(() =>
  documents.value.some(d => d.status === 'PENDING' || d.status === 'PROCESSING')
)
const inputPlaceholder = computed(() => {
  if (streaming.value) return 'AI 正在回答...'
  if (!hasAnyDoc.value) return '请先上传文档后再提问'
  if (!hasReadyDoc.value && hasProcessingDoc.value) return '文档解析中，请稍候...'
  if (!hasReadyDoc.value) return '文档尚未解析完成，请稍候...'
  return '输入你的问题，回车发送（Shift+Enter 换行）'
})
const inputDisabled = computed(() => streaming.value || !hasReadyDoc.value)

/* ---------- 登录 ---------- */
async function doLogin() {
  if (!username.value.trim()) return ElMessage.warning('请输入用户名')
  logining.value = true
  try {
    const data = await login(username.value)
    setToken(data.token)
    logged.value = true
    ElMessage.success('登录成功')
    await init()
  } catch (e) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    logining.value = false
  }
}

function logout() {
  clearToken()
  logged.value = false
  username.value = ''
  sessions.value = []
  documents.value = []
  messages.value = []
  currentSessionId.value = null
  ElMessage.success('已退出')
}

/* ---------- 初始化 ---------- */
async function init() {
  await Promise.all([loadSessions(), loadDocuments()])
}

async function loadSessions() {
  try { sessions.value = await listSessions() } catch (e) { console.warn(e) }
}

async function loadDocuments() {
  try { documents.value = await listDocuments() } catch (e) { console.warn(e) }
}

/* ---------- 会话 ---------- */
async function newChat() {
  const data = await createSession('新对话')
  sessions.value.unshift({ id: data.sessionId, title: data.title })
  selectSession(data.sessionId)
}

async function selectSession(id) {
  currentSessionId.value = id
  const s = sessions.value.find(x => x.id === id)
  currentTitle.value = s ? s.title : ''
  try {
    const list = await listMessages(id)
    messages.value = list.map(m => ({ ...m, refs: m.references || '' }))
  } catch (e) {
    messages.value = []
  }
  scrollBottom()
}

async function removeSession(id) {
  try {
    await ElMessageBox.confirm('确定删除该会话？', '提示', { type: 'warning' })
    await deleteSession(id)
    sessions.value = sessions.value.filter(s => s.id !== id)
    if (currentSessionId.value === id) {
      currentSessionId.value = null
      messages.value = []
      currentTitle.value = ''
    }
    ElMessage.success('已删除')
  } catch (e) { /* cancelled */ }
}

/* ---------- 文档 ---------- */
async function customUpload({ file }) {
  uploading.value = true
  try {
    const data = await uploadDocument(file)
    documents.value.unshift(data)
    ElMessage.success('上传成功，后台正在解析向量化...')
    pollDocStatus()
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function pollDocStatus() {
  const timer = setInterval(async () => {
    await loadDocuments()
    const pending = documents.value.some(d => d.status === 'PENDING' || d.status === 'PROCESSING')
    if (!pending) clearInterval(timer)
  }, 3000)
  setTimeout(() => clearInterval(timer), 120000)
}

async function removeDoc(id) {
  try {
    await ElMessageBox.confirm('确定删除该文档？', '提示', { type: 'warning' })
    await deleteDocument(id)
    documents.value = documents.value.filter(d => d.id !== id)
    ElMessage.success('已删除')
  } catch (e) { /* cancelled */ }
}

function statusText(s) {
  return { PENDING: '排队中', PROCESSING: '解析中', DONE: '已完成', FAILED: '失败' }[s] || s
}

/* ---------- 发送消息（SSE 流式） ---------- */
async function askDemo(q) {
  input.value = q
  await send()
}

async function send() {
  const q = input.value.trim()
  if (!q || streaming.value) return

  const tmpId = Date.now()
  messages.value.push({ _tmp: tmpId, role: 'USER', content: q })
  input.value = ''
  const aiMsg = { _tmp: tmpId + 1, role: 'ASSISTANT', content: '', refs: '' }
  messages.value.push(aiMsg)
  streaming.value = true
  scrollBottom()

  await streamChat('/api/chat/ask/stream',
    { sessionId: currentSessionId.value, question: q },
    {
      onSession: (sid) => {
        if (!currentSessionId.value) {
          currentSessionId.value = Number(sid)
          sessions.value.unshift({ id: Number(sid), title: q.slice(0, 20) })
          currentTitle.value = q.slice(0, 20)
        }
      },
      onMeta: (refs) => {
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'ASSISTANT') {
          last.refs = refs || ''
        }
      },
      onToken: (t) => {
        const last = messages.value[messages.value.length - 1]
        last.content += t
        scrollBottom()
      },
      onDone: () => {
        streaming.value = false
      },
      onError: (e) => {
        streaming.value = false
        const last = messages.value[messages.value.length - 1]
        if (last && !last.content) last.content = '> 回答失败：' + (e.message || '未知错误')
        ElMessage.error(e.message || '回答失败')
      }
    }
  )
}

/* ---------- 工具 ---------- */
function renderMd(text) {
  if (!text) return ''
  const html = marked.parse(text)
  return DOMPurify.sanitize(html)
}

function scrollBottom() {
  nextTick(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
  })
}

onMounted(() => {
  if (logged.value) init()
})
</script>

<style scoped>
/* ================== 全局变量 ================== */
.layout-vars {
  --sidebar-bg: #0f172a;
  --sidebar-bg-2: #1e293b;
  --sidebar-text: #cbd5e1;
  --sidebar-text-dim: #64748b;
  --sidebar-hover: #1e293b;
  --sidebar-active: #2563eb;
  --sidebar-border: #1e293b;
  --primary: #3b82f6;
  --primary-dark: #2563eb;
  --bg: #f7f7f8;
  --bg-card: #ffffff;
  --border: #e5e7eb;
  --text: #1f2937;
  --text-dim: #6b7280;
}

/* ================== 登录页 ================== */
.login-wrap {
  height: 100vh;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #312e81 100%);
  position: relative; overflow: hidden;
}
.login-wrap::before {
  content: ''; position: absolute; width: 600px; height: 600px; border-radius: 50%;
  background: radial-gradient(circle, rgba(59,130,246,.3), transparent 70%);
  top: -200px; right: -200px;
}
.login-wrap::after {
  content: ''; position: absolute; width: 500px; height: 500px; border-radius: 50%;
  background: radial-gradient(circle, rgba(139,92,246,.25), transparent 70%);
  bottom: -150px; left: -150px;
}
.login-card {
  position: relative; z-index: 1;
  width: 420px; padding: 40px 36px; background: #fff;
  border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,.3);
  display: flex; flex-direction: column; gap: 14px;
}
.login-logo {
  width: 64px; height: 64px; border-radius: 16px; margin: 0 auto 8px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: #fff; box-shadow: 0 8px 20px rgba(59,130,246,.4);
}
.login-title { text-align: center; font-size: 24px; color: #0f172a; margin: 0; }
.login-subtitle { text-align: center; color: #6b7280; font-size: 13px; margin: 0 0 12px; }
.login-btn { width: 100%; height: 44px; font-size: 15px; font-weight: 500; margin-top: 4px; }
.login-tip { text-align: center; color: #9ca3af; font-size: 12px; margin: 0; }

/* ================== 主布局 ================== */
.app-layout {
  height: 100vh; display: flex; overflow: hidden;
  background: var(--bg, #f7f7f8);
}

/* ================== 侧边栏 ================== */
.sidebar {
  width: 280px; flex-shrink: 0;
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  display: flex; flex-direction: column;
  border-right: 1px solid var(--sidebar-border);
}

/* Brand */
.sidebar-brand {
  display: flex; align-items: center; gap: 12px;
  padding: 18px 20px; border-bottom: 1px solid var(--sidebar-border);
}
.brand-icon {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: #fff; box-shadow: 0 4px 12px rgba(59,130,246,.4);
}
.brand-text { line-height: 1.2; min-width: 0; }
.brand-title { font-size: 15px; font-weight: 600; color: #f1f5f9; }
.brand-sub { font-size: 11px; color: var(--sidebar-text-dim); margin-top: 2px; }

/* 新建对话 */
.sidebar-new { padding: 16px 16px 8px; }
.new-chat-btn {
  width: 100% !important; height: 42px !important;
  display: flex !important; align-items: center; justify-content: center; gap: 6px;
  font-weight: 600 !important; font-size: 14px !important;
  border-radius: 10px !important;
  color: #ffffff !important;
  background: linear-gradient(135deg, #4f8cff 0%, #6e6ef0 50%, #8b5cf6 100%) !important;
  border: none !important;
  box-shadow: 0 4px 14px rgba(79, 140, 255, 0.35), inset 0 1px 0 rgba(255,255,255,0.15) !important;
  transition: all .2s ease !important;
  letter-spacing: 0.5px;
}
.new-chat-btn:hover {
  background: linear-gradient(135deg, #5b97ff 0%, #7d7dff 50%, #9d6dff 100%) !important;
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(79, 140, 255, 0.5), inset 0 1px 0 rgba(255,255,255,0.2) !important;
}
.new-chat-btn:active { transform: translateY(0); }

/* 滚动区 */
.sidebar-scroll {
  flex: 1; overflow-y: auto; padding: 0 0 16px;
}
.sidebar-scroll::-webkit-scrollbar { width: 6px; }
.sidebar-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
.sidebar-scroll::-webkit-scrollbar-track { background: transparent; }

.sidebar-section { margin-top: 16px; padding: 0 16px; }
.section-header {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--sidebar-text-dim);
  font-weight: 600; text-transform: uppercase; letter-spacing: .5px;
  padding: 0 4px 8px;
}
.section-count {
  margin-left: auto; background: #334155; color: #94a3b8;
  font-size: 10px; padding: 1px 6px; border-radius: 8px;
  font-weight: 500; letter-spacing: 0; text-transform: none;
}

/* 会话列表 */
.session-list { display: flex; flex-direction: column; gap: 2px; }
.session-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 6px; cursor: pointer;
  font-size: 13px; color: var(--sidebar-text);
  transition: all .15s; position: relative;
}
.session-item:hover { background: var(--sidebar-hover); color: #f1f5f9; }
.session-item:hover .session-del { opacity: 1; }
.session-item.active {
  background: var(--sidebar-active); color: #fff;
  box-shadow: 0 2px 8px rgba(37,99,235,.3);
}
.session-icon { font-size: 14px; flex-shrink: 0; opacity: .8; }
.session-title {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.session-del {
  font-size: 14px; opacity: 0; padding: 2px;
  border-radius: 4px; transition: all .15s;
}
.session-del:hover { background: rgba(239,68,68,.2); color: #fca5a5; }

/* 上传 */
.upload-trigger { display: block; }
.upload-trigger :deep(.el-upload) { display: block; width: 100%; }
.upload-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 14px 12px;
  border: 1.5px dashed #8b5cf6;
  border-radius: 10px;
  color: #d8c5ff;
  font-size: 12px; font-weight: 500;
  cursor: pointer;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.12) 0%, rgba(99, 102, 241, 0.08) 100%);
  box-shadow: inset 0 0 0 1px rgba(139, 92, 246, 0.1);
  transition: all .2s ease;
}
.upload-btn:hover {
  border-color: #a78bfa;
  color: #ffffff;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.22) 0%, rgba(99, 102, 241, 0.18) 100%);
  box-shadow: 0 4px 14px rgba(139, 92, 246, 0.25), inset 0 0 0 1px rgba(167, 139, 250, 0.2);
  transform: translateY(-1px);
}
.upload-btn:active { transform: translateY(0); }

/* 文档列表 */
.doc-list { margin-top: 8px; display: flex; flex-direction: column; gap: 2px; max-height: 220px; overflow-y: auto; }
.doc-list::-webkit-scrollbar { width: 4px; }
.doc-list::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
.doc-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 5px;
  font-size: 12px; transition: background .15s;
}
.doc-item:hover { background: var(--sidebar-hover); }
.doc-item:hover .doc-del { opacity: 1; }
.doc-icon { color: #94a3b8; flex-shrink: 0; }
.doc-meta { flex: 1; min-width: 0; }
.doc-name {
  color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px;
}
.doc-status { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #64748b; margin-top: 2px; }
.status-dot {
  width: 6px; height: 6px; border-radius: 50%; background: #64748b; flex-shrink: 0;
}
.status-dot.status-pending { background: #94a3b8; }
.status-dot.status-processing { background: #fbbf24; animation: pulse 1.2s infinite; }
.status-dot.status-done { background: #34d399; }
.status-dot.status-failed { background: #f87171; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
.doc-del { font-size: 13px; opacity: 0; padding: 2px; border-radius: 3px; transition: all .15s; }
.doc-del:hover { background: rgba(239,68,68,.2); color: #fca5a5; }

.empty-hint {
  display: flex; align-items: center; gap: 6px; justify-content: center;
  padding: 16px 8px; color: var(--sidebar-text-dim); font-size: 12px;
}
.empty-hint.small { padding: 10px; }

/* 底部用户 */
.sidebar-footer {
  border-top: 1px solid var(--sidebar-border); padding: 12px;
}
.user-card {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border-radius: 8px; cursor: pointer;
  transition: background .15s;
}
.user-card:hover { background: var(--sidebar-hover); }
.user-avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  color: #fff; flex-shrink: 0;
}
.user-info { flex: 1; min-width: 0; }
.user-name { font-size: 13px; color: #f1f5f9; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-action { font-size: 11px; color: var(--sidebar-text-dim); margin-top: 2px; }
.user-card:hover .user-action { color: #94a3b8; }

/* ================== 主区 ================== */
.main-area {
  flex: 1; display: flex; flex-direction: column;
  background: var(--bg, #f7f7f8); min-width: 0;
}

/* 顶栏 */
.topbar {
  height: 60px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 28px; background: #fff;
  border-bottom: 1px solid var(--border, #e5e7eb);
  box-shadow: 0 1px 2px rgba(0,0,0,.02);
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.topbar-title { font-size: 16px; font-weight: 600; color: #1f2937; }
.topbar-tag {
  display: inline-flex !important; align-items: center; gap: 4px !important;
  background: #eff6ff !important; color: #2563eb !important;
  border: 1px solid #dbeafe !important;
}
.topbar-right { display: flex; align-items: center; gap: 16px; }
.topbar-icon {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 16px;
  background: #f3f4f6; color: #6b7280; font-size: 12px; font-weight: 500;
}
.topbar-icon span { color: #1f2937; font-weight: 600; }

/* 聊天容器 */
.chat-container {
  flex: 1; overflow: hidden; display: flex; justify-content: center;
  background: linear-gradient(180deg, #f7f7f8 0%, #fafafa 100%);
}
.messages {
  flex: 1; max-width: 860px; width: 100%;
  padding: 24px 28px; overflow-y: auto;
}
.messages::-webkit-scrollbar { width: 8px; }
.messages::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }
.messages::-webkit-scrollbar-track { background: transparent; }

/* 欢迎界面 */
.welcome {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 60px 20px; text-align: center;
}
.welcome-logo {
  width: 80px; height: 80px; border-radius: 20px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: #fff; box-shadow: 0 12px 30px rgba(59,130,246,.35);
  margin-bottom: 20px;
}
.welcome-title { font-size: 28px; color: #1f2937; margin: 0 0 8px; font-weight: 600; }
.welcome-desc { color: #6b7280; font-size: 14px; margin: 0 0 32px; }
.welcome-cards { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
.welcome-card {
  width: 180px; padding: 20px; background: #fff;
  border: 1px solid #e5e7eb; border-radius: 12px;
  cursor: pointer; transition: all .2s; text-align: left;
}
.welcome-card:hover {
  border-color: #3b82f6; transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(59,130,246,.15);
}
.welcome-card .el-icon { color: #3b82f6; margin-bottom: 12px; }
.card-title { font-size: 14px; font-weight: 600; color: #1f2937; margin-bottom: 4px; }
.card-desc { font-size: 12px; color: #6b7280; }

/* 消息 */
.msg-row {
  display: flex; gap: 14px; margin-bottom: 24px; align-items: flex-start;
  animation: fadeIn .3s ease;
}
.msg-row.user { flex-direction: row-reverse; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.msg-avatar {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: #fff; box-shadow: 0 2px 8px rgba(0,0,0,.08);
}
.msg-row.user .msg-avatar {
  background: linear-gradient(135deg, #10b981, #059669);
}
.msg-body { max-width: 75%; min-width: 0; }
.msg-row.user .msg-body { display: flex; flex-direction: column; align-items: flex-end; }
.msg-meta { margin-bottom: 4px; padding: 0 4px; }
.msg-row.user .msg-meta { text-align: right; }
.msg-author {
  font-size: 12px; color: #6b7280; font-weight: 500;
}
.msg-bubble {
  padding: 12px 16px; border-radius: 12px;
  background: #fff; border: 1px solid #e5e7eb;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
  word-break: break-word; line-height: 1.7;
}
.msg-row.user .msg-bubble {
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: #fff; border: none;
}
.msg-row.user .msg-bubble :deep(*) { color: inherit; }
.msg-row.user .msg-bubble :deep(pre) { background: rgba(0,0,0,.2); }
.msg-row.user .msg-bubble :deep(:not(pre) > code) { background: rgba(255,255,255,.2); color: #fff; }

/* 引用来源 */
.msg-refs {
  display: inline-flex; align-items: center; gap: 4px;
  margin-top: 6px; padding: 3px 10px;
  background: #eff6ff; border: 1px solid #dbeafe;
  border-radius: 8px; font-size: 12px; color: #2563eb;
  max-width: 100%;
}
.msg-refs .el-icon { color: #3b82f6; flex-shrink: 0; }
.refs-label { font-weight: 500; flex-shrink: 0; }
.refs-docs { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 输入区 */
.input-wrap {
  flex-shrink: 0; padding: 16px 28px 20px;
  background: #fff; border-top: 1px solid var(--border, #e5e7eb);
  display: flex; flex-direction: column; align-items: center;
}
.input-card {
  width: 100%; max-width: 860px;
  display: flex; gap: 10px; align-items: flex-end;
  padding: 8px 8px 8px 14px;
  background: #f9fafb; border: 1.5px solid #e5e7eb; border-radius: 16px;
  transition: all .2s;
}
.input-card:focus-within {
  border-color: #3b82f6; background: #fff;
  box-shadow: 0 0 0 3px rgba(59,130,246,.1);
}
.chat-input :deep(.el-textarea__inner) {
  background: transparent !important; border: none !important;
  box-shadow: none !important; padding: 8px 4px !important;
  font-size: 14px; resize: none;
}
.send-btn {
  height: 40px !important; padding: 0 18px !important;
  border-radius: 10px !important; font-weight: 500 !important;
  background: linear-gradient(135deg, #3b82f6, #6366f1) !important;
  border: none !important; flex-shrink: 0;
}
.send-btn:hover:not(:disabled) { opacity: .9; transform: translateY(-1px); }
.send-btn:disabled { background: #d1d5db !important; }
.input-hint {
  margin-top: 8px; font-size: 11px; color: #9ca3af; text-align: center;
}
</style>
