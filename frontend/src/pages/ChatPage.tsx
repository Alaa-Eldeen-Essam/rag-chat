import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import { ChatMessageBubble, ChatRole } from '../components/ChatMessage';
import { useSettings, ModelKind } from '../settings/SettingsContext';
import { UploadModal } from '../components/UploadModal';
import { useHttpClient } from '../lib/httpClient';
import { useStreamClient } from '../lib/streamClient';
import { t } from '../i18n/ui';

interface Conversation {
  id: number;
  title?: string | null;
  is_pinned?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

interface MessageSource {
  file_name?: string;
  location?: string;
  page?: number;
  excerpt_index?: number;
  snippet?: string;
  asset_id?: number;
}

interface GroupedSources {
  key: string;
  title: string;
  count: number;
  sources: MessageSource[];
}

interface HistoryMessage {
  id: string;
  role: ChatRole;
  content: string;
  sources?: MessageSource[];
  timestamp?: string | null;
}

interface ConversationsResponse {
  conversations?: {
    conversation_id: number;
    title?: string | null;
    is_pinned?: boolean;
    created_at?: string | null;
    updated_at?: string | null;
  }[];
}

interface ConversationHistoryResponse {
  history?: {
    id: number;
    prompt: string;
    answer: string;
    timestamp?: string | null;
    resources?: MessageSource[];
  }[];
}

interface AssetSummaryOption {
  asset_id: number;
  name?: string;
  original_name?: string;
  doc_type?: string;
}

interface AssetsResponse {
  assets?: AssetSummaryOption[];
}
export const ChatPage: React.FC = () => {
  const {
    defaultProjectId,
    currentDocType,
    chatMode,
    uiLanguage,
    docTypesVersion,
    setSettings,
    apiBaseUrl
  } = useSettings();
  const { request } = useHttpClient();
  const { streamFetch } = useStreamClient();
  const CONVERSATIONS_PER_PAGE = 5;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] =
    useState<number | null>(null);
  const [selectedConversationIdsForDelete, setSelectedConversationIdsForDelete] =
    useState<number[]>([]);
  const [pinnedConversationIds, setPinnedConversationIds] = useState<number[]>([]);
  const [conversationTab, setConversationTab] = useState<'all' | 'pinned'>('all');
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [search, setSearch] = useState('');
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [assetFilterIds, setAssetFilterIds] = useState<number[]>([]);
  const [showSummary, setShowSummary] = useState(false);
  const [summaryAssetId, setSummaryAssetId] = useState<number | null>(null);
  const [summaryText, setSummaryText] = useState('');
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryFocus, setSummaryFocus] = useState('');
  const [summaryModel] = useState<ModelKind>('best');
  const [summaryAssets, setSummaryAssets] = useState<AssetSummaryOption[]>([]);
  const [summaryDepth, setSummaryDepth] = useState<'short' | 'normal' | 'detailed'>('normal');
  const [feedbackByMessage, setFeedbackByMessage] = useState<
    Record<string, 'helpful' | 'unhelpful'>
  >({});
  const [expandedResourcesByMessage, setExpandedResourcesByMessage] = useState<Record<string, boolean>>({});
  const [openResourcePanel, setOpenResourcePanel] = useState<{
    messageId: string;
    fileKey: string;
  } | null>(null);
  const [docTypes, setDocTypes] = useState<string[]>([]);
  const [summaryWidth, setSummaryWidth] = useState<number>(320);
  const [isResizingSummary, setIsResizingSummary] = useState(false);
  const summaryRef = useRef<HTMLDivElement | null>(null);
  const [summaryFileQuery, setSummaryFileQuery] = useState('');
  const [conversationPage, setConversationPage] = useState(1);
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);
  const [docTypeError, setDocTypeError] = useState<string | null>(null);
  const [modeError, setModeError] = useState<string | null>(null);
  const [promptGuardMessage, setPromptGuardMessage] = useState<string | null>(null);
  const MODE_INFO_KEY = 'chat_regular_mode_info_shown';
  const [hasSeenRegularInfo, setHasSeenRegularInfo] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return window.localStorage.getItem(MODE_INFO_KEY) === '1';
  });
  const [showRegularInfoBanner, setShowRegularInfoBanner] = useState(false);
  const isRegularMode = chatMode === 'regular';
  const isMultihopMode = chatMode === 'multihop';
  const [multihopHops, setMultihopHops] = useState<number>(2);
  const [multihopK, setMultihopK] = useState<number>(6);
  const [multihopEvidence, setMultihopEvidence] = useState<number>(3);
  const uiText = (key: Parameters<typeof t>[1]) => t(uiLanguage, key);
  const isRTL = uiLanguage === 'ar';
  const buildResourceUrl = useCallback(
    (src: MessageSource) => {
      if (!apiBaseUrl) return null;
      const rawId = src.asset_id;
      const assetId =
        typeof rawId === 'number' ? rawId : Number(rawId);
      if (!Number.isFinite(assetId)) return null;
      const base = apiBaseUrl.replace(/\/$/, '');
      const fileName = (src.file_name || '').toLowerCase();
      const isPdf = fileName.endsWith('.pdf');
      const pageNo =
        typeof src.page === 'number' ? src.page : Number(src.page);
      const url = `${base}/api/v1/data/assets/${assetId}/file`;
      if (isPdf && Number.isFinite(pageNo) && pageNo > 0) {
        return `${url}#page=${pageNo}`;
      }
      return url;
    },
    [apiBaseUrl]
  );

  const pinnedSet = useMemo(() => new Set(pinnedConversationIds), [pinnedConversationIds]);

  useEffect(() => {
    const pinned = conversations
      .filter(c => c.is_pinned)
      .map(c => c.id);
    setPinnedConversationIds(pinned);
  }, [conversations]);

  const filteredConversations = useMemo(() => {
    const list = Array.isArray(conversations) ? conversations : [];
    const filtered = list.filter(conv =>
      (conv.title || '').toLowerCase().includes(search.toLowerCase())
    );
    const sorted = [...filtered].sort((a, b) => {
      const aDate =
        a.updated_at || a.created_at
          ? new Date(a.updated_at || a.created_at || '').getTime()
          : 0;
      const bDate =
        b.updated_at || b.created_at
          ? new Date(b.updated_at || b.created_at || '').getTime()
          : 0;
      return bDate - aDate;
    });
    if (conversationTab === 'pinned') {
      return sorted.filter(conv => pinnedSet.has(conv.id));
    }
    return sorted;
  }, [conversations, search, conversationTab, pinnedSet]);

  const totalConversationPages = useMemo(() => {
    if (filteredConversations.length === 0) return 1;
    return Math.max(
      1,
      Math.ceil(filteredConversations.length / CONVERSATIONS_PER_PAGE)
    );
  }, [filteredConversations, CONVERSATIONS_PER_PAGE]);

  const pagedConversations = useMemo(() => {
    if (filteredConversations.length === 0) return [];
    const safePage = Math.min(
      Math.max(conversationPage, 1),
      totalConversationPages
    );
    const start = (safePage - 1) * CONVERSATIONS_PER_PAGE;
    const end = start + CONVERSATIONS_PER_PAGE;
    return filteredConversations.slice(start, end);
  }, [
    filteredConversations,
    conversationPage,
    totalConversationPages,
    CONVERSATIONS_PER_PAGE
  ]);

  const filteredSummaryAssets = useMemo(() => {
    const query = summaryFileQuery.trim().toLowerCase();
    if (!query) return summaryAssets;
    return summaryAssets.filter(a => {
      const name =
        (a.original_name || a.name || `asset-${a.asset_id}`).toLowerCase();
      const docType = (a.doc_type || '').toLowerCase();
      return name.includes(query) || docType.includes(query);
    });
  }, [summaryAssets, summaryFileQuery]);

  const filteredDocTypes = useMemo(() => {
    const assetDocTypes = new Set(summaryAssets.map(a => a.doc_type).filter(Boolean));
    return docTypes.filter(dt => assetDocTypes.has(dt));
  }, [docTypes, summaryAssets]);

  const chatAssetsForCurrentDocType = useMemo(() => {
    if (chatMode === 'regular') return [];
    if (!currentDocType || currentDocType.trim() === '') return [];
    const dt = currentDocType.trim().toLowerCase();
    return summaryAssets.filter(
      a => (a.doc_type || '').trim().toLowerCase() === dt
    );
  }, [summaryAssets, currentDocType, chatMode]);

  const [fileDropdownOpen, setFileDropdownOpen] = useState(false);
  const [fileDropdownQuery, setFileDropdownQuery] = useState('');

  const filteredChatAssetsForCurrentDocType = useMemo(() => {
    const list = chatAssetsForCurrentDocType;
    const q = fileDropdownQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter(a => {
      const name =
        (a.original_name || a.name || `asset-${a.asset_id}`).toLowerCase();
      return name.includes(q);
    });
  }, [chatAssetsForCurrentDocType, fileDropdownQuery]);

  const groupSourcesByFile = useCallback((sources: MessageSource[]): GroupedSources[] => {
    const groups: Record<string, GroupedSources> = {};
    sources.forEach((src, idx) => {
      const title =
        (src.file_name && src.file_name.trim()) ||
        (src.excerpt_index != null
          ? `${uiText('asset')} #${src.excerpt_index}`
          : `${uiText('asset')} #${idx + 1}`);
      const key = title.toLowerCase();
      if (!groups[key]) {
        groups[key] = { key, title, count: 0, sources: [] };
      }
      groups[key].sources.push(src);
      groups[key].count += 1;
    });
    return Object.values(groups);
  }, [uiText]);

  // When the global doc type changes (via the header dropdown),
  // reset any per-chat file filters and related search query so
  // the filter always reflects the currently selected doc type.
  useEffect(() => {
    setAssetFilterIds([]);
    setFileDropdownQuery('');
  }, [currentDocType]);

  useEffect(() => {
    // Reset or clamp page when the number of conversations changes
    setConversationPage(prev => {
      const maxPage = Math.max(
        1,
        Math.ceil(
          (filteredConversations.length || 0) / CONVERSATIONS_PER_PAGE
        )
      );
      if (prev > maxPage) return maxPage;
      if (prev < 1) return 1;
      return prev;
    });
  }, [filteredConversations.length, CONVERSATIONS_PER_PAGE]);

  const selectedAssetLabel = useMemo(() => {
    if (!assetFilterIds.length) return '';
    if (assetFilterIds.length === 1) {
      const asset = summaryAssets.find(a => a.asset_id === assetFilterIds[0]);
      if (!asset) return `${uiText('asset')} #${assetFilterIds[0]}`;
      return (
        asset.original_name ||
        asset.name ||
        `${uiText('asset')} #${assetFilterIds[0]}`
      );
    }
    return `${assetFilterIds.length} ${uiText('filesSelected')}`;
  }, [assetFilterIds, summaryAssets, uiText]);

  useEffect(() => {
    if (!openResourcePanel) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpenResourcePanel(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [openResourcePanel]);

  useEffect(() => {
    if (!isResizingSummary) return;

    const handleMove = (e: MouseEvent) => {
      if (!summaryRef.current) return;
      const parent = summaryRef.current.parentElement;
      if (!parent) return;
      const parentRect = parent.getBoundingClientRect();

      const rawWidth = parentRect.right - e.clientX;
      const minWidth = 220;
      const maxWidth = Math.max(260, parentRect.width - 260);
      const clamped = Math.min(Math.max(rawWidth, minWidth), maxWidth);
      setSummaryWidth(clamped);
    };

    const handleUp = () => {
      setIsResizingSummary(false);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);

    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isResizingSummary]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const projectParam = params.get('project');
    const assetParam = params.get('asset_id');
    const modeParam = params.get('mode');
    if (projectParam) {
      setSettings(prev => ({
        ...prev,
        defaultProjectId: projectParam
      }));
    }
    if (assetParam) {
      const parsed = Number(assetParam);
      if (Number.isFinite(parsed)) {
        setAssetFilterIds([parsed]);
        setSummaryAssetId(parsed);
      }
    }
    if (modeParam === 'summary') {
      setShowSummary(true);
    }

    request<ConversationsResponse>('/api/v1/nlp/conversations')
      .then(res => {
        const items = Array.isArray(res.conversations) ? res.conversations : [];
        const mapped: Conversation[] = items.map(conv => ({
          id: conv.conversation_id,
          title: conv.title,
          is_pinned: !!conv.is_pinned,
          created_at: conv.created_at,
          updated_at: conv.updated_at
        }));
        setConversations(mapped);
      })
      .catch(() => {
        setConversations([]);
      });
  }, [request, setSettings]);

  useEffect(() => {
    request<AssetsResponse>('/api/v1/data/assets')
      .then(res => {
        const items = Array.isArray(res.assets) ? res.assets : [];
        setSummaryAssets(items);
      })
      .catch(() => setSummaryAssets([]));
  }, [request, docTypesVersion, currentDocType]);

  useEffect(() => {
    if (isRegularMode && !hasSeenRegularInfo) {
      setShowRegularInfoBanner(true);
    }
    if (!isRegularMode) {
      setShowRegularInfoBanner(false);
    }
  }, [isRegularMode, hasSeenRegularInfo]);

  const loadHistory = async (id: number) => {
    setSelectedConversationId(id);
    try {
      const res = await request<ConversationHistoryResponse>(
        `/api/v1/nlp/conversations/${id}/history?limit=5`
      );
      const historyItems = Array.isArray(res.history) ? res.history : [];
      const mapped: HistoryMessage[] = [];
      historyItems.forEach(item => {
        if (item.prompt) {
          mapped.push({
            id: `prompt-${item.id}`,
            role: 'user',
            content: item.prompt,
            timestamp: item.timestamp
          });
        }
        if (item.answer) {
          mapped.push({
            id: `answer-${item.id}`,
            role: 'assistant',
            content: item.answer,
            timestamp: item.timestamp,
            // For historical messages, use persisted resources from the
            // conversation history payload. Fallback to an empty array so
            // the UI logic can rely on a consistent type.
            sources: Array.isArray(item.resources) ? item.resources : []
          });
        }
      });
      setMessages(mapped);
    } catch {
      setMessages([]);
    }
  };

  const handleNewChat = () => {
    setSelectedConversationId(null);
    setMessages([]);
  };

  const handleRenameConversation = async (id: number) => {
    const current = conversations.find(c => c.id === id);
    if (!current) return;
    setRenameTarget(current);
    setRenameTitle(current.title || uiText('conversationTitle'));
  };

  const handleDeleteConversation = async (id: number) => {
    const current = conversations.find(c => c.id === id);
    if (!current) return;
    setDeleteTarget(current);
  };

  const toggleConversationSelection = (id: number) => {
    setSelectedConversationIdsForDelete(prev => {
      if (prev.includes(id)) {
        return prev.filter(existingId => existingId !== id);
      }
      return [...prev, id];
    });
  };

  const togglePinnedConversation = async (id: number) => {
    const current = conversations.find(c => c.id === id);
    const nextPinned = current ? !current.is_pinned : true;
    setConversations(prev =>
      prev.map(c => (c.id === id ? { ...c, is_pinned: nextPinned } : c))
    );
    try {
      await request(`/api/v1/nlp/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_pinned: nextPinned })
      });
    } catch {
      // revert on failure
      setConversations(prev =>
        prev.map(c => (c.id === id ? { ...c, is_pinned: current?.is_pinned } : c))
      );
    }
  };
  const toggleResourcesForMessage = (messageId: string) => {
    setExpandedResourcesByMessage(prev => ({
      ...prev,
      [messageId]: !prev[messageId]
    }));
  };

  const handleModeChange = (nextMode: 'rag' | 'regular' | 'multihop') => {
    if (nextMode === chatMode) return;
    if (isStreaming) {
      setIsStreaming(false);
    }
    setMessages([]);
    setSelectedConversationId(null);
    setOpenResourcePanel(null);
    setExpandedResourcesByMessage({});
    setAssetFilterIds([]);
    setFileDropdownQuery('');
    setDocTypeError(null);
    setPromptGuardMessage(null);
    setUploadMessage(null);
    setShowSummary(false);
    setSummaryAssetId(null);
    setSummaryText('');
    setSettings(prev => ({
      ...prev,
      chatMode: nextMode
    }));
    if (nextMode === 'regular' && !hasSeenRegularInfo) {
      setHasSeenRegularInfo(true);
      setShowRegularInfoBanner(true);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(MODE_INFO_KEY, '1');
      }
    } else {
      setShowRegularInfoBanner(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;
    const modeForRequest = chatMode;
    const sendingRegular = modeForRequest === 'regular';
    const sendingMultihop = modeForRequest === 'multihop';
    if (!sendingRegular && (!currentDocType || currentDocType.trim() === '')) {
      setDocTypeError(uiText('selectDocTypeFirst'));
      return;
    }
    setDocTypeError(null);
    setModeError(null);
    const userText = input.trim();
    setInput('');

    const userMsg: HistoryMessage = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: userText,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMsg]);
    setIsStreaming(true);

    let assistantId = `assistant-${Date.now()}`;

    const requestBody: Record<string, any> = {
      text: userText,
      limit: 20,
      model: 'best',
      conversation_id: selectedConversationId ?? undefined,
      stream: true,
      mode: modeForRequest
    };
    if (!sendingRegular) {
      requestBody.doc_type = currentDocType;
      if (assetFilterIds && assetFilterIds.length > 0) {
        requestBody.asset_ids = assetFilterIds;
      }
    }
    if (sendingMultihop) {
      // Client-side validation to surface friendly errors early.
      if (
        multihopHops < 1 ||
        multihopHops > 5 ||
        multihopK < 1 ||
        multihopK > 20 ||
        multihopEvidence < 1 ||
        multihopEvidence > multihopK
      ) {
        setModeError(uiText('multihopParamError'));
        setIsStreaming(false);
        return;
      }
      requestBody.multihop_hops = multihopHops;
      requestBody.multihop_k = multihopK;
      requestBody.multihop_per_hop_evidence = multihopEvidence;
    }

    await streamFetch(
      `/api/v1/nlp/index/answer/${defaultProjectId}`,
      {
        method: 'POST',
        body: JSON.stringify(requestBody)
      },
  {
    onStart: () => {
      assistantId = `assistant-${Date.now()}`;
      setMessages(prev => [
        ...prev,
        { id: assistantId, role: 'assistant', content: '', timestamp: new Date().toISOString() }
      ]);
    },
        onDelta: (delta, _event) => {
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantId
                ? { ...m, content: m.content + delta }
                : m
            )
          );
        },
        onDone: final => {
          setIsStreaming(false);
          if (
            final &&
            typeof final.message_id === 'number' &&
            Number.isFinite(final.message_id)
          ) {
            const newId = String(final.message_id);
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantId ? { ...m, id: newId } : m
              )
            );
            assistantId = newId;
          }
          if (final && typeof final.answer === 'string') {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: final.answer as string,
                      sources: Array.isArray(final.sources)
                        ? (final.sources as any)
                        : m.sources
                    }
                  : m
              )
            );
          }
          if (!sendingRegular && final && Array.isArray(final.sources)) {
            // If we can't find the assistant message by id (id may have
            // changed during streaming), fall back to the last assistant
            // message in the list to ensure sources render.
            setMessages(prev => {
              let updated = false;
              const next = prev.map(m => {
                if (m.id === assistantId && m.role === 'assistant') {
                  updated = true;
                  return { ...m, sources: final.sources as any };
                }
                return m;
              });
              if (!updated) {
                for (let i = next.length - 1; i >= 0; i -= 1) {
                  if (next[i].role === 'assistant') {
                    next[i] = { ...next[i], sources: final.sources as any };
                    break;
                  }
                }
              }
              return next;
            });
          }
          const convId =
            typeof final?.conversation_id === 'number'
              ? final.conversation_id
              : Number(final?.conversation_id);
          if (convId && Number.isFinite(convId)) {
            setSelectedConversationId(convId);
          }
          request<ConversationsResponse>('/api/v1/nlp/conversations')
            .then(res => {
              const items = Array.isArray(res.conversations)
                ? res.conversations
                : [];
              const mapped: Conversation[] = items.map(conv => ({
                id: conv.conversation_id,
                title: conv.title,
                is_pinned: !!conv.is_pinned,
                created_at: conv.created_at,
                updated_at: conv.updated_at
              }));
              setConversations(mapped);
            })
            .catch(() => {});
        },
        onError: errorPayload => {
          setIsStreaming(false);
          if (errorPayload && typeof errorPayload === 'object') {
            const signal = (errorPayload as any).signal as string | undefined;
            const detail =
              typeof (errorPayload as any).detail === 'string'
                ? (errorPayload as any).detail
                : undefined;
            if (signal === 'prompt_rejected') {
              setPromptGuardMessage(detail || uiText('promptGuardBlocked'));
              return;
            }
            if (detail) {
              setPromptGuardMessage(detail);
              return;
            }
          }
          if (errorPayload instanceof Error) {
            setPromptGuardMessage(errorPayload.message);
            return;
          }
          setPromptGuardMessage(uiText('friendlyServerIssue'));
        }
      }
    );
  };

  const submitFeedback = (messageId: string, isHelpful: boolean) => {
    const match = String(messageId).match(/(\d+)$/);
    const numericId = match ? Number(match[1]) : NaN;

    // Only send feedback for messages that have a real int32 DB id.
    if (
      !Number.isFinite(numericId) ||
      numericId <= 0 ||
      numericId > 2147483647
    ) {
      return;
    }

    request('/api/v1/stats/feedback', {
      method: 'POST',
      body: JSON.stringify({
        message_id: numericId,
        is_helpful: isHelpful
      })
    })
      .then(() => {
        setFeedbackByMessage(prev => ({
          ...prev,
          [messageId]: isHelpful ? 'helpful' : 'unhelpful'
        }));
      })
      .catch(() => {
        // silent failure; stats are non-critical
      });
  };

  const formatTimestamp = (value?: string | null) => {
    if (!value) return '';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '';
    return parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const formatDateLabel = (value?: string | null) => {
    if (!value) return '';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '';
    const now = new Date();
    const startOfDay = (date: Date) => {
      return new Date(date.getFullYear(), date.getMonth(), date.getDate());
    };
    const diffMs = startOfDay(now).getTime() - startOfDay(parsed).getTime();
    const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return uiText('dateToday');
    if (diffDays === 1) return uiText('dateYesterday');
    if (diffDays > 1 && diffDays <= 6) {
      return parsed.toLocaleDateString(uiLanguage === 'ar' ? 'ar' : undefined, {
        weekday: 'long'
      });
    }
    return parsed.toLocaleDateString(uiLanguage === 'ar' ? 'ar' : undefined, {
      day: 'numeric',
      month: 'long',
      year: 'numeric'
    });
  };

  useEffect(() => {
    request<{ doc_types?: string[] }>('/api/v1/nlp/doc-types')
      .then(res => {
        const list = Array.isArray(res.doc_types) ? res.doc_types : [];
        setDocTypes(list);
      })
      .catch(() => setDocTypes([]));
  }, [request, docTypesVersion]);

  const activeResourcePanel = useMemo(() => {
    if (!openResourcePanel || isRegularMode) return null;
    const msg = messages.find(m => m.id === openResourcePanel.messageId);
    if (!msg || !msg.sources) return null;
    const grouped = groupSourcesByFile(msg.sources || []);
    const group =
      grouped.find(g => g.key === openResourcePanel.fileKey) || grouped[0];
    if (!group) return null;
    return { group, messageId: msg.id };
  }, [groupSourcesByFile, messages, openResourcePanel, isRegularMode]);

  return (
    <>
      <Sidebar>
        <div className="flex items-center justify-between mb-2">
          <div>
            <div className="text-[11px] uppercase tracking-wide text-slate-400">
              {uiText('conversations')}
            </div>
            <div className="text-xs text-slate-500">
              {filteredConversations.length} {uiText('navChat')} • {pinnedConversationIds.length} pinned
            </div>
          </div>
          <button
            type="button"
            onClick={handleNewChat}
            className="btn-primary-rounded px-3 py-1.5 text-[11px]"
          >
            + {uiText('newChat')}
          </button>
        </div>
        <div className="flex items-center gap-2 mb-2">
          <div className="inline-flex items-center rounded-full bg-white border border-[color:var(--border-subtle)] p-1">
            <button
              type="button"
              onClick={() => setConversationTab('all')}
              className={`px-3 py-1 text-[11px] rounded-full ${
                conversationTab === 'all'
                  ? 'bg-[color:var(--accent)] text-white shadow'
                  : 'text-slate-600 hover:text-[color:var(--accent-strong)]'
              }`}
            >
              {uiLanguage === 'ar' ? 'الكل' : 'All'}
            </button>
            <button
              type="button"
              onClick={() => setConversationTab('pinned')}
              className={`px-3 py-1 text-[11px] rounded-full ${
                conversationTab === 'pinned'
                  ? 'bg-[color:var(--accent)] text-white shadow'
                  : 'text-slate-600 hover:text-[color:var(--accent-strong)]'
              }`}
            >
              {uiLanguage === 'ar' ? 'المثبتة' : 'Pinned'}
            </button>
          </div>
          <button
            type="button"
            onClick={() => setShowUpload(true)}
            className="text-[11px] rounded-full border border-[color:var(--border-subtle)] px-3 py-1 bg-white text-slate-700 hover:border-[color:var(--accent)]"
          >
            {uiText('upload')}
          </button>
        </div>
        <div className="flex items-center gap-2 mb-2">
          <input
            placeholder={uiText('search')}
            className="flex-1 rounded-full bg-white border border-[color:var(--border-subtle)] px-3 py-1.5 text-[11px] focus:outline-none focus:ring-2 focus:ring-[color:var(--accent)]"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            type="button"
            disabled={selectedConversationIdsForDelete.length === 0}
            onClick={() => setShowBulkDeleteConfirm(true)}
            className="btn-action btn-action-danger px-3 py-1 text-[11px] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uiText('deleteSelected')}
          </button>
        </div>
        <div className="rounded-2xl border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] px-3 py-2 text-[11px] text-slate-600 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="uppercase tracking-wide text-slate-400">
              {uiText('docType')}
            </span>
            <span className="app-pill bg-white border border-[color:var(--border-subtle)] text-slate-700">
              {currentDocType && currentDocType.trim() !== ''
                ? currentDocType
                : uiText('allFiles')}
            </span>
          </div>
          <span className="text-[10px] text-slate-400">
            {uiText('page')} {Math.min(conversationPage, totalConversationPages)} / {totalConversationPages}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto space-y-2 pr-1 text-xs mt-2">
          {filteredConversations.length === 0 && (
            <div className="text-slate-400 text-xs app-card-soft p-3 rounded-xl border border-[color:var(--border-subtle)]">
              {uiText('noConversations')}
            </div>
          )}
          {pagedConversations.map(conv => {
            const isSelected = conv.id === selectedConversationId;
            const isPinned = pinnedSet.has(conv.id);
            return (
              <div
                key={conv.id}
                className={`w-full px-3 py-2 rounded-2xl border flex flex-col gap-2 transition ${
                  isSelected
                    ? 'border-[color:var(--accent)] bg-[color:var(--bg-soft)] shadow'
                    : 'border-[color:var(--border-subtle)] bg-white hover:border-[color:var(--accent)]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="mr-1 h-3 w-3 accent-[color:var(--accent-strong)]"
                    checked={selectedConversationIdsForDelete.includes(conv.id)}
                    onChange={() => toggleConversationSelection(conv.id)}
                  />
                  <button
                    type="button"
                    onClick={() => loadHistory(conv.id)}
                    className="flex-1 text-left min-w-0"
                  >
                    <div className="truncate text-slate-900 font-semibold">
                      {conv.title || uiText('conversationTitle')}
                    </div>
                    <div className="text-[10px] text-slate-400 flex items-center gap-2">
                      {conv.updated_at
                        ? new Date(conv.updated_at).toLocaleString()
                        : conv.created_at
                        ? new Date(conv.created_at).toLocaleString()
                        : uiText('startChat')}
                      {isPinned && (
                        <span className="app-pill bg-[color:var(--accent)] text-white">
                          {uiLanguage === 'ar' ? 'مثبت' : 'Pinned'}
                        </span>
                      )}
                    </div>
                  </button>
                </div>
                <div className="flex items-center justify-between text-[11px] text-slate-500 gap-2">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => togglePinnedConversation(conv.id)}
                      className={`btn-chip px-3 py-1 text-[11px] ${
                        isPinned ? 'btn-chip-active' : ''
                      }`}
                    >
                      {isPinned ? (uiLanguage === 'ar' ? 'إلغاء التثبيت' : 'Unpin') : uiLanguage === 'ar' ? 'تثبيت' : 'Pin'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRenameConversation(conv.id)}
                      className="text-theme-accent"
                    >
                      {uiText('rename')}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteConversation(conv.id)}
                    className="btn-action btn-action-danger px-3 py-1 text-[11px]"
                  >
                    {uiText('delete')}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        {filteredConversations.length > 0 && (
          <div className="mt-3 flex items-center justify-between text-[10px] text-slate-500">
            <button
              type="button"
              className="px-3 py-1 rounded-full border border-[color:var(--border-subtle)] bg-white hover:border-[color:var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
              disabled={conversationPage <= 1}
              onClick={() =>
                setConversationPage(prev => Math.max(prev - 1, 1))
              }
            >
              {uiText('previous')}
            </button>
            <span>
              {uiText('page')} {Math.min(conversationPage, totalConversationPages)} {uiText('of')}{' '}
              {totalConversationPages}
            </span>
            <button
              type="button"
              className="px-3 py-1 rounded-full border border-[color:var(--border-subtle)] bg-white hover:border-[color:var(--accent)] disabled:opacity-40 disabled:cursor-not-allowed"
              disabled={conversationPage >= totalConversationPages}
              onClick={() =>
                setConversationPage(prev =>
                  Math.min(prev + 1, totalConversationPages)
                )
              }
            >
              {uiText('next')}
            </button>
          </div>
        )}
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <button
            type="button"
            onClick={() => setShowSummary(prev => !prev)}
            className="rounded-2xl px-3 py-2 border border-[color:var(--border-subtle)] bg-white text-slate-700 hover:border-[color:var(--accent)]"
          >
            {showSummary ? uiText('hideSummary') : uiText('showSummary')}
          </button>
          <button
            type="button"
            onClick={() => setShowUpload(true)}
            className="rounded-2xl px-3 py-2 border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] text-slate-700 hover:border-[color:var(--accent)]"
          >
            {uiText('upload')}
          </button>
        </div>
      </Sidebar>
      <section className="flex-1 flex flex-col gap-3 min-h-full">
        <div className="app-card-soft px-5 py-4 rounded-3xl flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-col gap-1">
              <div className="text-sm font-semibold text-[color:var(--text-surface)]">
                {uiText('chat')}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{uiText('mode')}:</span>
                <div className="inline-flex items-center rounded-full border border-[color:var(--border-subtle)] bg-white p-1 flex-wrap gap-1">
                  <button
                    type="button"
                    onClick={() => handleModeChange('rag')}
                    className={`px-3 py-1 text-[11px] rounded-full ${
                      chatMode === 'rag'
                        ? 'bg-[color:var(--accent)] text-white shadow'
                        : 'text-slate-600 hover:text-[color:var(--accent-strong)]'
                    }`}
                  >
                    {uiText('filesMode')}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleModeChange('regular')}
                    className={`px-3 py-1 text-[11px] rounded-full ${
                      chatMode === 'regular'
                        ? 'bg-[color:var(--accent)] text-white shadow'
                        : 'text-slate-600 hover:text-[color:var(--accent-strong)]'
                    }`}
                  >
                    {uiText('regularChat')}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleModeChange('multihop')}
                    className={`px-3 py-1 text-[11px] rounded-full ${
                      chatMode === 'multihop'
                        ? 'bg-[color:var(--accent)] text-white shadow'
                        : 'text-slate-600 hover:text-[color:var(--accent-strong)]'
                    }`}
                  >
                    {uiText('multihopRag')}
                  </button>
                </div>
              </div>
              </div>
            </div>
            {!isRegularMode && (
              <div className="flex flex-col gap-1 text-xs text-slate-500">
                <span>{uiText('docType')}:</span>
                <select
                  className="rounded-full border border-[color:var(--border-subtle)] bg-white px-3 py-1 text-[12px] text-slate-700"
                  value={currentDocType}
                  onChange={e =>
                    setSettings(prev => ({
                      ...prev,
                      currentDocType: e.target.value
                    }))
                  }
                >
                  {filteredDocTypes.map(dt => (
                    <option key={dt} value={dt}>
                      {dt}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {isMultihopMode && (
              <div
                className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500"
                title={uiText('multihopHelp')}
              >
                <label className="flex items-center gap-1">
                  <span>{uiText('multihopHops')}</span>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={multihopHops}
                    onChange={e => setMultihopHops(Math.max(1, Math.min(5, Number(e.target.value) || 1)))}
                    className="w-14 rounded-full border border-[color:var(--border-subtle)] px-2 py-1 text-[11px]"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span>{uiText('multihopTopK')}</span>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    value={multihopK}
                    onChange={e => setMultihopK(Math.max(1, Math.min(12, Number(e.target.value) || 1)))}
                    className="w-14 rounded-full border border-[color:var(--border-subtle)] px-2 py-1 text-[11px]"
                  />
                </label>
                <label className="flex items-center gap-1">
                  <span>{uiText('multihopEvidence')}</span>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    value={multihopEvidence}
                    onChange={e => setMultihopEvidence(Math.max(1, Math.min(12, Number(e.target.value) || 1)))}
                    className="w-16 rounded-full border border-[color:var(--border-subtle)] px-2 py-1 text-[11px]"
                  />
                </label>
                <div className="w-full text-[11px] text-slate-400">
                  {uiText('multihopHelp')}
                </div>
                {modeError && (
                  <div className="text-[11px] text-red-500 font-medium w-full">
                    {modeError}
                  </div>
                )}
              </div>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  if (isRegularMode) return;
                  setShowSummary(prev => !prev);
                }}
                disabled={isRegularMode}
                className={`rounded-full px-3 py-2 text-[11px] border border-[color:var(--border-subtle)] ${
                  isRegularMode
                    ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                    : 'bg-white text-slate-700 hover:border-[color:var(--accent)]'
                }`}
              >
                {showSummary ? uiText('hideSummary') : uiText('showSummary')}
              </button>
            </div>
          </div>
          {showRegularInfoBanner && isRegularMode && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2 text-[11px] text-amber-800">
              {uiText('regularInfo')}
            </div>
          )}
          {!isRegularMode && (
            <div className={`relative flex flex-wrap items-center gap-3 ${isRTL ? 'flex-row-reverse' : ''}`}>
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border-subtle)] bg-white px-4 py-2 text-[12px] text-slate-700 hover:border-[color:var(--accent)]"
              onClick={() => setFileDropdownOpen(prev => !prev)}
            >
              {assetFilterIds.length === 0
                ? `${uiText('allFiles')} (${chatAssetsForCurrentDocType.length})`
                : selectedAssetLabel}
              <span className="text-slate-400">
                {fileDropdownOpen ? '▴' : '▾'}
              </span>
            </button>
            {assetFilterIds.length > 0 && (
              <button
                type="button"
                className="text-[11px] text-slate-500 underline"
                onClick={() => setAssetFilterIds([])}
              >
                {uiText('clear')}
              </button>
            )}
            {fileDropdownOpen && (
              <div
                className={`absolute ${
                  isRTL ? 'left-0' : 'right-auto'
                } top-full mt-2 w-72 rounded-2xl border border-[color:var(--border-subtle)] bg-white shadow-xl z-20 ${
                  isRTL ? 'text-right' : ''
                }`}
              >
                <div className="p-3 border-b border-[color:var(--border-subtle)]">
                  <input
                    type="text"
                    className="w-full rounded-full bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-3 py-1 text-[11px] placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
                    placeholder={uiText('searchFiles')}
                    value={fileDropdownQuery}
                    onChange={e => setFileDropdownQuery(e.target.value)}
                  />
                </div>
                <div className="max-h-64 overflow-y-auto text-[11px]">
                  {filteredChatAssetsForCurrentDocType.length === 0 && (
                    <div className="px-3 py-2 text-slate-400">
                      {uiText('noFilesForType')}
                    </div>
                  )}
                  {filteredChatAssetsForCurrentDocType.map(a => {
                    const checked = assetFilterIds.includes(a.asset_id);
                    return (
                      <label
                        key={a.asset_id}
                        className={`flex items-center gap-2 px-3 py-1.5 hover:bg-[color:var(--bg-soft)] cursor-pointer ${
                          isRTL ? 'flex-row-reverse' : ''
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="h-3 w-3 accent-[color:var(--accent)]"
                          checked={checked}
                          onChange={e => {
                            const checkedNow = e.target.checked;
                            setAssetFilterIds(prev => {
                              if (checkedNow) {
                                if (prev.includes(a.asset_id)) return prev;
                                return [...prev, a.asset_id];
                              }
                              return prev.filter(
                                id => id !== a.asset_id
                              );
                            });
                          }}
                        />
                        <span className="truncate text-slate-700">
                          {a.original_name ||
                            a.name ||
                            `${uiText('asset')} #${a.asset_id}`}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
            {uploadMessage && (
              <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-4 py-1 text-[11px] text-emerald-700">
                <span>{uploadMessage}</span>
                <button
                  type="button"
                  className="text-emerald-300 hover:text-emerald-100 text-[10px]"
                  onClick={() => setUploadMessage(null)}
                >
                  {uiText('dismiss')}
                </button>
              </div>
            )}
            {docTypeError && (
              <div className="text-[11px] text-amber-600">
                {docTypeError}
              </div>
            )}
            {promptGuardMessage && (
              <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-4 py-1 text-[11px] text-amber-700">
                <span>{promptGuardMessage}</span>
                <button
                  type="button"
                  className="text-amber-400 hover:text-amber-600 text-[10px]"
                  onClick={() => setPromptGuardMessage(null)}
                >
                  {uiText('dismiss')}
                </button>
              </div>
            )}
          </div>
          )}
        </div>
        <div className="flex-1 flex flex-col lg:flex-row gap-4">
          <div className="flex-1 app-card bg-white flex flex-col rounded-3xl overflow-hidden">
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              {messages.length === 0 && (
                <div className="app-card-soft p-4 rounded-2xl border border-[color:var(--border-subtle)]">
                  <div className="text-sm font-semibold text-slate-900 mb-1">
                    {uiLanguage === 'ar'
                      ? 'ابدأ محادثة جديدة'
                      : 'Start a fresh conversation'}
                  </div>
                  <div className="text-xs text-slate-500 mb-2">
                    {uiText('startChat')}
                  </div>
                </div>
              )}
              {(() => {
                let lastDate = '';
                return messages.map(m => {
                  const dateLabel = m.timestamp ? formatDateLabel(m.timestamp) : '';
                  const showDate = !!dateLabel && dateLabel !== lastDate;
                  if (showDate) lastDate = dateLabel;
                  return (
                    <React.Fragment key={m.id}>
                      {showDate && (
                        <div className="flex justify-center py-2">
                          <span className="px-4 py-1 rounded-full bg-[color:var(--bg-soft)] text-[11px] text-slate-600 border border-[color:var(--border-subtle)]">
                            {dateLabel}
                          </span>
                        </div>
                      )}
                      <div className="space-y-2">
                        <ChatMessageBubble
                          role={m.role}
                          content={m.content}
                          isStreaming={isStreaming && m.role === 'assistant'}
                          onCopy={() => {}}
                        />
                  {!isRegularMode &&
                    m.role === 'assistant' &&
                    m.sources &&
                    m.sources.length > 0 && (() => {
                      const grouped = groupSourcesByFile(m.sources || []);
                      const isExpanded = !!expandedResourcesByMessage[m.id];
                      return (
                        <div className="pl-4 md:pl-10">
                          <div className="rounded-2xl border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] px-4 py-3 text-[15px] text-slate-700 space-y-3">
                            <div
                              className={`flex flex-wrap items-center justify-between gap-2 cursor-pointer ${isRTL ? 'text-right' : 'text-left'}`}
                              role="button"
                              tabIndex={0}
                              onClick={() => toggleResourcesForMessage(m.id)}
                              onKeyDown={e => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  toggleResourcesForMessage(m.id);
                                }
                              }}
                            >
                              <div className="flex items-center gap-3">
                                <span className="font-semibold text-slate-900 text-base">
                                  {uiText('resources')} ({m.sources.length})
                                </span>
                                <span className="text-xs text-slate-500">
                                  {grouped.length} {uiLanguage === 'ar' ? 'ملفات' : 'files'}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 text-[11px]">
                                <span
                                  className="text-[11px] text-[color:var(--accent-strong)] underline hover:text-[color:var(--accent)]"
                                >
                                  {isExpanded
                                    ? uiLanguage === 'ar'
                                      ? 'إخفاء'
                                      : 'Hide'
                                    : uiLanguage === 'ar'
                                    ? 'عرض'
                                    : 'Show'}
                                </span>
                              </div>
                            </div>
                            {isExpanded && (
                              <div className="flex flex-wrap gap-2" dir={isRTL ? 'rtl' : 'ltr'}>
                                {grouped.map(group => (
                                  <button
                                    key={`${m.id}-${group.key}`}
                                    type="button"
                                    onClick={() =>
                                      setOpenResourcePanel({
                                        messageId: m.id,
                                        fileKey: group.key
                                      })
                                    }
                                    className="group flex items-center justify-between gap-3 rounded-xl border border-[color:var(--border-subtle)] bg-white px-3 py-2 shadow-sm hover:border-[color:var(--accent)] transition text-left min-w-[160px]"
                                  >
                                    <div className="flex-1 min-w-0">
                                      <div className="font-semibold text-[15px] text-slate-900 truncate group-hover:text-[color:var(--accent-strong)]">
                                        {group.title}
                                      </div>
                                      <div className="text-[11px] text-slate-500 truncate">
                                        {uiLanguage === 'ar' ? 'عرض المقاطع' : 'View excerpts'}
                                      </div>
                                    </div>
                                    <span className="inline-flex items-center justify-center rounded-full bg-[color:var(--bg-soft)] px-2 py-1 text-[11px] text-slate-700 border border-[color:var(--border-subtle)]">
                                      {group.count}
                                    </span>
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })()}
                        {m.role === 'assistant' && (
                          <div className="pl-4 md:pl-10 text-[11px] text-slate-500 flex gap-3">
                            {(() => {
                              const fb = feedbackByMessage[m.id];
                              const helpfulActive = fb === 'helpful';
                              const unhelpfulActive = fb === 'unhelpful';
                              const disabled = !!fb;
                              return (
                                <>
                                  <button
                                    type="button"
                                    className={
                                      helpfulActive
                                        ? 'text-emerald-500 font-semibold'
                                        : 'hover:text-emerald-500'
                                    }
                                    disabled={disabled}
                                    onClick={() => submitFeedback(m.id, true)}
                                  >
                                    {uiText('helpful')}
                                  </button>
                                  <button
                                    type="button"
                                    className={
                                      unhelpfulActive
                                        ? 'text-red-500 font-semibold'
                                        : 'hover:text-red-500'
                                    }
                                    disabled={disabled}
                                    onClick={() => submitFeedback(m.id, false)}
                                  >
                                    {uiText('notHelpful')}
                                  </button>
                                </>
                              );
                            })()}
                          </div>
                        )}
                      </div>
                    </React.Fragment>
                  );
                });
              })()}
            </div>
            <div className="border-t border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] px-5 py-4">
              <form
                className="flex flex-col gap-3"
                onSubmit={e => {
                  e.preventDefault();
                  handleSend();
                }}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    type="button"
                    className="rounded-full px-3 py-1 text-[12px] border border-[color:var(--border-subtle)] bg-white hover:border-[color:var(--accent)]"
                    onClick={() => setShowUpload(true)}
                  >
                    {uiText('upload')}
                  </button>
                </div>
                <textarea
                  className="flex-1 min-h-[80px] max-h-44 rounded-2xl bg-white border border-[color:var(--border-subtle)] px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[color:var(--accent)] resize-none"
                  placeholder={uiText('askQuestion')}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                />
                <div className="flex items-center justify-between">
                  <div className="text-[11px] text-slate-500">
                    {isStreaming ? (uiLanguage === 'ar' ? 'جاري البث...' : 'Streaming response...') : uiLanguage === 'ar' ? 'اضغط Enter للإرسال' : 'Press Enter to send'}
                  </div>
                  <button
                    type="submit"
                    disabled={isStreaming || !input.trim()}
                    className="btn-primary-rounded px-5 py-2 text-sm"
                  >
                    {uiText('send')}
                  </button>
                </div>
              </form>
            </div>
          </div>
          {showSummary && (
            <aside
              ref={summaryRef}
              className="w-full md:border-l border-t md:border-t-0 border-[color:var(--border-subtle)] px-4 py-3 flex flex-col gap-2 bg-white rounded-3xl shadow-md md:relative"
              style={{ width: summaryWidth, maxWidth: '100%' }}
            >
              <div
                className="hidden md:block absolute left-0 top-0 bottom-0 w-1 cursor-col-resize"
                onMouseDown={() => setIsResizingSummary(true)}
              >
                <div className="h-full w-[3px] bg-slate-700/60 hover:bg-[color:var(--accent-strong)] mx-auto rounded-full" />
              </div>
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-900">
                  {uiLanguage === 'ar' ? 'الرؤى والملخص' : 'Insights & Summary'}
                </div>
                <button
                  type="button"
                  className="text-[11px] text-slate-500 hover:text-[color:var(--accent-strong)]"
                  onClick={() => setShowSummary(false)}
                >
                  {uiText('close')}
                </button>
              </div>
              <label className="text-[11px] text-slate-500">
                <span className="block mb-1">{uiText('file')}</span>
                <input
                  type="text"
                  className="mb-1 w-full rounded-full bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-3 py-1 text-[11px] placeholder:text-slate-400"
                  placeholder={uiText('searchFiles')}
                  value={summaryFileQuery}
                  onChange={e => setSummaryFileQuery(e.target.value)}
                />
                <select
                  className="w-full rounded-xl bg-white border border-[color:var(--border-subtle)] px-3 py-1.5 text-xs"
                  value={summaryAssetId ?? ''}
                  onChange={e => {
                    const val = e.target.value;
                    if (!val) {
                      setSummaryAssetId(null);
                    } else {
                      const parsed = Number(val);
                      setSummaryAssetId(
                        Number.isFinite(parsed) ? parsed : null
                      );
                    }
                  }}
                >
                  <option value="">
                    {summaryAssets.length === 0
                      ? uiText('noFilesAvailable')
                      : uiText('selectFile')}
                  </option>
                  {filteredSummaryAssets.map(a => (
                    <option key={a.asset_id} value={a.asset_id}>
                      {a.original_name || a.name || `${uiText('asset')} #${a.asset_id}`}
                      {a.doc_type ? ` (${a.doc_type})` : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-slate-500">
                <span className="block mb-1">{uiText('summaryFocusLabel')}</span>
                <textarea
                  className="w-full rounded-xl bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-3 py-1.5 text-xs min-h-[60px]"
                  placeholder={uiText('summaryFocusPlaceholder')}
                  value={summaryFocus}
                  onChange={e => setSummaryFocus(e.target.value)}
                />
              </label>
              <div className="flex items-center gap-2">
                <label className="text-[11px] text-slate-500 flex-1">
                  <span className="block mb-1">{uiText('summaryDepthLabel')}</span>
                  <select
                    className="w-full rounded-xl bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-3 py-1.5 text-xs"
                    value={summaryDepth}
                    onChange={e =>
                      setSummaryDepth(
                        e.target.value as 'short' | 'normal' | 'detailed'
                      )
                    }
                  >
                    <option value="short">{uiText('summaryDepthShort')}</option>
                    <option value="normal">{uiText('summaryDepthNormal')}</option>
                    <option value="detailed">{uiText('summaryDepthDetailed')}</option>
                  </select>
                </label>
              </div>
              <button
                type="button"
                disabled={!summaryAssetId || summaryLoading}
                onClick={async () => {
                  if (!summaryAssetId || summaryLoading) return;
                  const maxOutputTokens =
                    summaryDepth === 'short'
                      ? 512
                      : summaryDepth === 'normal'
                      ? 1024
                      : 4096;
                  const selectedAsset = summaryAssets.find(
                    a => a.asset_id === summaryAssetId
                  );
                  const fileIdForSummary =
                    selectedAsset?.name || String(summaryAssetId);
                  setSummaryError(null);
                  setSummaryText('');
                  setSummaryLoading(true);
                  await streamFetch(
                    `/api/v1/nlp/summary/${defaultProjectId}`,
                    {
                      method: 'POST',
                      body: JSON.stringify({
                        file_id: fileIdForSummary,
                        max_chunks:
                          summaryDepth === 'short'
                            ? 50
                            : summaryDepth === 'normal'
                            ? 100
                            : 200,
                        focus: summaryFocus || null,
                        max_output_tokens: maxOutputTokens,
                        model: summaryModel,
                        stream: true
                      })
                    },
                    {
                      onStart: () => {
                        setSummaryText('');
                      },
                      onDelta: (delta, _event) => {
                        setSummaryText(prev => prev + delta);
                      },
                      onDone: final => {
                        setSummaryLoading(false);
                        if (
                          final &&
                          typeof final.summary === 'string' &&
                          final.summary.trim().length > 0
                        ) {
                          setSummaryText(final.summary as string);
                        }
                      },
                      onError: (err: any) => {
                        setSummaryLoading(false);
                        setSummaryError(
                          err?.detail ||
                            err?.message ||
                            uiText('summaryFailed')
                        );
                      }
                    }
                  );
                }}
                className="inline-flex items-center justify-center rounded-full bg-[color:var(--accent-strong)] px-4 py-2 text-xs font-medium text-white hover:bg-[color:var(--accent)] disabled:opacity-50"
              >
                {summaryLoading ? uiText('summarizing') : uiText('summarize')}
              </button>
              {summaryError && (
                <div className="text-[11px] text-red-500">
                  {summaryError}
                </div>
              )}
              <div className="mt-2 flex-1 min-h-[80px] max-h-64 overflow-y-auto rounded-xl border border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)] px-3 py-2 text-xs text-slate-900 whitespace-pre-wrap">
                {summaryLoading && summaryText.trim().length === 0 && (
                  <span className="text-slate-400">
                    {uiText('generatingSummary')}
                  </span>
                )}
                {summaryText.trim().length === 0 && !summaryLoading && (
                  <span className="text-slate-500">
                    {uiText('summaryWillAppear')}
                  </span>
                )}
                {summaryText.trim().length > 0 && summaryText}
              </div>
            </aside>
          )}
        </div>
      </section>
      {activeResourcePanel && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center md:justify-end bg-[rgba(15,23,42,0.4)] backdrop-blur-sm p-4"
          role="dialog"
          aria-modal="true"
          dir={isRTL ? 'rtl' : 'ltr'}
          onMouseDown={e => {
            if (e.target === e.currentTarget) {
              setOpenResourcePanel(null);
            }
          }}
        >
          <div
            className="w-full max-w-3xl md:max-w-xl h-[80vh] md:h-[90vh] rounded-3xl bg-white border border-[color:var(--border-subtle)] shadow-2xl flex flex-col overflow-hidden"
            onMouseDown={e => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[color:var(--border-subtle)] bg-[color:var(--bg-soft)]">
              <div className="min-w-0">
                <div className="text-lg font-semibold text-slate-900 truncate">
                  {activeResourcePanel.group.title}
                </div>
                <div className="text-[12px] text-slate-500">
                  {activeResourcePanel.group.count}{' '}
                  {uiLanguage === 'ar' ? 'مقتطفات' : 'excerpts'}
                </div>
              </div>
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border-subtle)] bg-white px-3 py-1.5 text-[12px] font-semibold text-[color:var(--accent-strong)] shadow-sm hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={() => setOpenResourcePanel(null)}
              >
                <span aria-hidden="true">×</span>
                <span className="text-[12px] font-semibold">{uiText('close')}</span>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 text-sm leading-relaxed">
              {activeResourcePanel.group.sources.map((src, idx) => {
                const loc =
                  src.page && Number.isFinite(src.page)
                    ? `${uiText('page')} ${src.page}`
                    : src.location && typeof src.location === 'string'
                    ? src.location
                    : `${uiText('excerpt')} ${idx + 1}`;
                const snippet = src.snippet || '';
                const resourceUrl = buildResourceUrl(src);
                return (
                  <div
                    key={`${activeResourcePanel.messageId}-panel-${idx}`}
                    className="rounded-2xl border border-[color:var(--border-subtle)] bg-white px-4 py-3 shadow-sm"
                  >
                    <div className={`flex items-center justify-between gap-2 ${isRTL ? 'flex-row-reverse' : ''}`}>
                      <div className="flex items-center gap-2 text-[12px] text-slate-600">
                        <span className="inline-flex items-center justify-center rounded-full bg-[color:var(--bg-soft)] px-2 py-1 text-[11px] text-slate-700 border border-[color:var(--border-subtle)]">
                          #{src.excerpt_index || idx + 1}
                        </span>
                        <span className="text-[12px] text-slate-500 truncate max-w-[160px]">
                          {loc}
                        </span>
                      </div>
                      {resourceUrl && (
                        <a
                          href={resourceUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[11px] text-[color:var(--accent-strong)] underline hover:text-[color:var(--accent)]"
                        >
                          {uiText('openFile')}
                        </a>
                      )}
                    </div>
                    {snippet && (
                      <div className="mt-2 text-[14px] leading-relaxed text-slate-800 whitespace-pre-wrap">
                        {snippet}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onSuccess={info => {
          setUploadMessage(info.message);
          if (info.assetId) {
            setAssetFilterIds([info.assetId]);
            setSummaryAssetId(info.assetId);
          }
          if (info.docType) {
            setSettings(prev => ({
              ...prev,
              currentDocType: info.docType as string
            }));
          }
        }}
      />
      {renameTarget && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-3xl bg-white border border-[color:var(--border-subtle)] p-5 shadow-2xl text-xs">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-[color:var(--text-surface)]">
                {uiText('rename')} {uiText('conversation')}
              </h2>
              <button
                type="button"
                onClick={() => setRenameTarget(null)}
                className="text-slate-400 hover:text-[color:var(--accent-strong)] text-xs"
              >
                {uiText('close')}
              </button>
            </div>
            <div className="space-y-3">
              <input
                className="w-full rounded-2xl bg-[color:var(--bg-soft)] border border-[color:var(--border-subtle)] px-3 py-2 text-sm"
                value={renameTitle}
                onChange={e => setRenameTitle(e.target.value)}
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="btn-chip px-4 py-2"
                  onClick={() => setRenameTarget(null)}
                >
                  {uiText('cancel')}
                </button>
                <button
                  type="button"
                  className="btn-action px-4 py-2"
                  onClick={async () => {
                    const title = renameTitle.trim();
                    if (!title) return;
                    try {
                      await request(`/api/v1/nlp/conversations/${renameTarget.id}`, {
                        method: 'PATCH',
                        body: JSON.stringify({ title })
                      });
                      setConversations(prev =>
                        prev.map(c =>
                          c.id === renameTarget.id ? { ...c, title } : c
                        )
                      );
                    } catch {
                      // ignore for now
                    } finally {
                      setRenameTarget(null);
                    }
                  }}
                >
                  {uiText('save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {showBulkDeleteConfirm && selectedConversationIdsForDelete.length > 0 && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.45)] backdrop-blur-sm p-4">
          <div className="app-card w-full max-w-sm p-5 text-xs space-y-3">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-[color:var(--text-surface)] mb-1">
                {uiText('deleteSelectedConversationsTitle')}
              </h2>
              <p className="text-slate-500 text-sm">
                {uiText('deleteSelectedConversationsBody')}{' '}
                ({selectedConversationIdsForDelete.length})
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-chip px-4 py-2"
                onClick={() => setShowBulkDeleteConfirm(false)}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="btn-action btn-action-danger px-4 py-2"
                onClick={async () => {
                  const idsToDelete = [...selectedConversationIdsForDelete];
                  try {
                    await Promise.all(
                      idsToDelete.map(id =>
                        request(`/api/v1/nlp/conversations/${id}`, {
                          method: 'DELETE'
                        })
                      )
                    );
                    setConversations(prev =>
                      prev.filter(c => !idsToDelete.includes(c.id))
                    );
                    setPinnedConversationIds(prev =>
                      prev.filter(id => !idsToDelete.includes(id))
                    );
                    if (
                      selectedConversationId !== null &&
                      idsToDelete.includes(selectedConversationId)
                    ) {
                      setSelectedConversationId(null);
                      setMessages([]);
                    }
                  } catch {
                    // ignore for now
                  } finally {
                    setShowBulkDeleteConfirm(false);
                    setSelectedConversationIdsForDelete([]);
                  }
                }}
              >
                {uiText('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
      {deleteTarget && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.45)] backdrop-blur-sm p-4">
          <div className="app-card w-full max-w-sm p-5 text-xs space-y-3">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-[color:var(--text-surface)] mb-1">
                {uiText('deleteConversationTitle')}
              </h2>
              <p className="text-slate-500 text-sm">
                {uiText('deleteConversationBody')} &quot;{deleteTarget.title ||
                  uiText('conversationTitle')}&quot;
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="btn-chip px-4 py-2"
                onClick={() => setDeleteTarget(null)}
              >
                {uiText('cancel')}
              </button>
              <button
                type="button"
                className="btn-action btn-action-danger px-4 py-2"
                onClick={async () => {
                  try {
                    await request(`/api/v1/nlp/conversations/${deleteTarget.id}`, {
                      method: 'DELETE'
                    });
                    setConversations(prev =>
                      prev.filter(c => c.id !== deleteTarget.id)
                    );
                    setPinnedConversationIds(prev =>
                      prev.filter(id => id !== deleteTarget.id)
                    );
                    if (selectedConversationId === deleteTarget.id) {
                      setSelectedConversationId(null);
                      setMessages([]);
                    }
                  } catch {
                    // ignore for now
                  } finally {
                    setDeleteTarget(null);
                  }
                }}
              >
                {uiText('delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
