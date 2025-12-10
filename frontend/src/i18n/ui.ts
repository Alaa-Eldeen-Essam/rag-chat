export type UILanguage = 'en' | 'ar';

type Key =
  // General / nav / common
  | 'chat'
  | 'navChat'
  | 'navStats'
  | 'navSummaries'
  | 'navAdminFiles'
  | 'navAdminUsers'
  | 'navLogin'
  | 'navSignup'
  | 'navFiles'
  | 'logout'
  | 'docType'
  | 'search'
  | 'loading'
  | 'previous'
  | 'next'
  | 'page'
  | 'yes'
  | 'no'
  | 'id'
  | 'name'
  | 'size'
  | 'visibility'
  | 'actions'
  | 'all'
  | 'private'
  | 'public'
  | 'global'
  | 'asset'
  | 'conversation'
  | 'department'
  | 'created'
  | 'lastLogin'
  | 'total'
  | 'goToChat'
  | 'bytes'
  | 'close'
  | 'edit'
  | 'dismiss'
  | 'of'
  | 'source'
  | 'excerpt'
  | 'friendlyServerIssue'
  // Chat
  | 'resources'
  | 'allFiles'
  | 'filesSelected'
  | 'noFilesForType'
  | 'searchFiles'
  | 'startChat'
  | 'helpful'
  | 'notHelpful'
  | 'upload'
  | 'showSummary'
  | 'hideSummary'
  | 'clear'
  | 'noConversations'
  | 'conversationTitle'
  | 'newChat'
  | 'rename'
  | 'delete'
  | 'send'
  // Auth
  | 'loginTitle'
  | 'loginSubtitle'
  | 'username'
  | 'password'
  | 'login'
  | 'signingIn'
  | 'invalidCredentials'
  | 'signupTitle'
  | 'signupSubtitle'
  | 'signupSubmit'
  | 'backToLogin'
  | 'signupValidationUserPass'
  | 'signupValidationUserLen'
  | 'signupValidationPassLen'
  | 'signupSuccess'
  | 'signupFailed'
  | 'signupUserExists'
  // Admin Users
  | 'adminUsers'
  | 'createUser'
  | 'role'
  | 'create'
  | 'loadingUsers'
  | 'noUsers'
  | 'searchUsers'
  | 'searchUsersPlaceholder'
  | 'resetPassword'
  | 'save'
  | 'cancel'
  | 'admin'
  | 'user'
  | 'totalUsersLabel'
  // Admin Files
  | 'adminFiles'
  | 'searchAssets'
  | 'searchAssetsPlaceholder'
  | 'refresh'
  | 'deleteSelected'
  | 'loadingAssets'
  | 'noAssets'
  | 'bulkDeleteTitle'
  | 'bulkDeleteConfirm'
  | 'totalAssetsLabel'
  // Upload modal
  | 'uploadTitle'
  | 'selectFiles'
  | 'docTypePlaceholder'
  | 'docTypePlaceholderRequired'
  | 'docTypeRequired'
  | 'visibilityLabel'
  | 'privateOnlyYou'
  | 'departmentVisibility'
  | 'globalVisibility'
  | 'isPrivate'
  | 'departmentLabel'
  | 'chooseExisting'
  | 'enterNew'
  | 'searchDepartmentsPlaceholder'
  | 'newDepartmentPlaceholder'
  | 'submitUpload'
  | 'cancelUpload'
  | 'uploading'
  | 'processingIndexing'
  | 'chunks'
  | 'noFilesSelected'
  | 'uploadSuccessSingle'
  | 'uploadSuccessMulti'
  | 'uploadFailed'
  | 'selectDocTypeFirst'
  // Summaries
  | 'summaries'
  | 'generateSummary'
  | 'summaryFocusPlaceholder'
  | 'summaryFocusLabel'
  | 'summaryDepthLabel'
  | 'summaryDepthShort'
  | 'summaryDepthNormal'
  | 'summaryDepthDetailed'
  | 'documentSummary'
  | 'file'
  | 'noFilesAvailable'
  | 'selectFile'
  | 'summarize'
  | 'summarizing'
  | 'generatingSummary'
  | 'summaryWillAppear'
  | 'summaryFailed'
  | 'confirmDeleteSummary'
  | 'deleteSummaryTitle'
  | 'deleteSummaryBody'
  | 'summariesBulkDeleteTitle'
  | 'summariesBulkDeleteBody'
  // Stats
  | 'stats'
  | 'myStats'
  | 'usersTab'
  | 'systemTab'
  | 'totalQueries'
  | 'totalDocuments'
  | 'totalUsers'
  | 'totalConversations'
  | 'newUsers'
  | 'averageResponse'
  | 'dailyActive'
  | 'weeklyActive'
  | 'newUsers7d'
  | 'documentsByType'
  | 'queriesByDepartment'
  | 'documentsByVisibility'
  | 'topUsersByQueries'
  | 'averageRating'
  | 'conversationLengths'
  | 'loadingStats'
  | 'noStats'
  | 'queries'
  | 'users'
  | 'documents'
  | 'conversations'
  | 'totalQueriesLabel'
  | 'dau'
  | 'wau'
  | 'contentRisk'
  | 'queriesLabel'
  | 'avgMs'
  | 'lastActive'
  | 'noUserStats'
  | 'noSystemStats'
  | 'noUsersMatch'
  | 'fallback'
  | 'deleteConversationTitle'
  | 'deleteConversationBody'
  | 'deleteSelectedConversationsTitle'
  | 'deleteSelectedConversationsBody'
  | 'askQuestion'
  | 'model'
  | 'summaryDetails'
  | 'saved'
  | 'selectSummary'
  | 'loadingSummary'
  | 'noSummaries'
  | 'summarizeAction'
  | 'deleteFileTitle'
  | 'deleteFileBody'
  | 'deleteAll';

const STRINGS: Record<UILanguage, Record<Key, string>> = {
  en: {
    chat: 'Chat',
    navChat: 'Chat',
    navStats: 'Stats',
    navSummaries: 'Summaries',
    navAdminFiles: 'Admin Files',
    navAdminUsers: 'Admin Users',
    navLogin: 'Login',
    navSignup: 'Sign up',
    navFiles: 'Files',
    logout: 'Logout',
    docType: 'Doc type',
    search: 'Search...',
    loading: 'Loading...',
    previous: 'Previous',
    next: 'Next',
    page: 'Page',
    yes: 'Yes',
    no: 'No',
    id: 'ID',
    name: 'Name',
    size: 'Size',
    visibility: 'Visibility',
    actions: 'Actions',
    all: 'All',
    private: 'Private',
    public: 'Public',
    global: 'Global',
    asset: 'Asset',
    conversation: 'Conversation',
    department: 'Department',
    created: 'Created',
    lastLogin: 'Last login',
    total: 'Total',
    goToChat: 'Go to chat',
    bytes: 'bytes',
    close: 'Close',
    edit: 'Edit',
    dismiss: 'Dismiss',
    of: 'of',
    source: 'Source',
    excerpt: 'Excerpt',
    friendlyServerIssue: "We're still tidying things up. Please try again shortly.",
    resources: 'Resources',
    allFiles: 'All files',
    filesSelected: 'files selected',
    noFilesForType: 'No files for this type.',
    searchFiles: 'Search files...',
    startChat: 'Start a new chat to begin.',
    helpful: '👍Helpful',
    notHelpful: '👎Not helpful',
    upload: 'Upload',
    showSummary: 'Show Summary Panel',
    hideSummary: 'Hide Summary Panel',
    clear: 'clear',
    noConversations: 'No conversations yet. Start a new chat.',
    conversationTitle: 'Conversation',
    newChat: 'New Chat',
    rename: 'Rename',
    delete: 'Delete',
    send: 'Send',
    loginTitle: 'Military Assistant Login',
    loginSubtitle: 'Enter your Basic Auth credentials to continue.',
    username: 'Username',
    password: 'Password',
    login: 'Login',
    signingIn: 'Signing in...',
    invalidCredentials: 'Invalid username or password',
    signupTitle: 'Create Account',
    signupSubtitle: 'This creates a new user account on the backend.',
    signupSubmit: 'Sign up',
    backToLogin: 'Back to login',
    signupValidationUserPass: 'Please enter a username and password.',
    signupValidationUserLen: 'Username must be at least 3 characters long.',
    signupValidationPassLen: 'Password must be at least 6 characters long.',
    signupSuccess: 'User created. You can now log in.',
    signupFailed: 'Signup failed',
    signupUserExists: 'This username is already taken. Please choose another.',
    adminUsers: 'Admin Users',
    createUser: 'Create user',
    role: 'Role',
    create: 'Create',
    loadingUsers: 'Loading users...',
    noUsers: 'No users found.',
    searchUsers: 'Search users...',
    searchUsersPlaceholder: 'Search by username or department...',
    resetPassword: 'Reset password',
    save: 'Save',
    cancel: 'Cancel',
    admin: 'Admin',
    user: 'User',
    totalUsersLabel: 'Total users',
    adminFiles: 'Admin Files',
    searchAssets: 'Search by name or type...',
    searchAssetsPlaceholder: 'Search by name or type...',
    refresh: 'Refresh',
    deleteSelected: 'Delete selected',
    loadingAssets: 'Loading assets...',
    noAssets: 'No assets available.',
    bulkDeleteTitle: 'Delete selected items',
    bulkDeleteConfirm: 'This will permanently remove the selected items.',
    totalAssetsLabel: 'Total assets',
    uploadTitle: 'Upload and Index Files',
    selectFiles: 'Select files',
    docTypePlaceholder: 'Or enter a new document type...',
    docTypePlaceholderRequired: 'Enter document type (required)...',
    docTypeRequired: 'Document type is required.',
    visibilityLabel: 'Visibility',
    privateOnlyYou: 'Private (only you)',
    departmentVisibility: 'Department',
    globalVisibility: 'Global',
    isPrivate: 'Private file',
    departmentLabel: 'Department',
    chooseExisting: 'Use existing',
    enterNew: 'Enter new',
    searchDepartmentsPlaceholder: 'Type to search departments...',
    newDepartmentPlaceholder: 'Enter a new department name...',
    submitUpload: 'Upload',
    cancelUpload: 'Cancel',
    uploading: 'Uploading...',
    processingIndexing: 'Processing & indexing...',
    chunks: 'chunks',
    noFilesSelected: 'No files selected',
    uploadSuccessSingle: 'File uploaded, processed, and indexed successfully.',
    uploadSuccessMulti: 'Uploaded and indexed files successfully.',
    uploadFailed: 'Upload failed',
    selectDocTypeFirst: 'Please select a document type before chatting.',
    summaries: 'Summaries',
    generateSummary: 'Generate summary',
    summaryFocusPlaceholder: 'E.g., key responsibilities, risks, or high-level overview.',
    summaryFocusLabel: 'Focus (optional)',
    summaryDepthLabel: 'Summary depth',
    summaryDepthShort: 'Short overview',
    summaryDepthNormal: 'Normal summary',
    summaryDepthDetailed: 'Detailed summary',
    documentSummary: 'Document Summary',
    file: 'File',
    noFilesAvailable: 'No files available',
    selectFile: 'Select a file',
    summarize: 'Summarize',
    summarizing: 'Summarizing...',
    generatingSummary: 'Generating summary...',
    summaryWillAppear: 'Summary will appear here.',
    summaryFailed: 'Failed to generate summary.',
    confirmDeleteSummary: 'This will permanently remove this summary.',
    stats: 'Stats',
    myStats: 'My Stats',
    usersTab: 'Users',
    systemTab: 'System',
    totalQueries: 'Total Queries',
    totalDocuments: 'Documents',
    totalUsers: 'Users',
    totalConversations: 'Conversations',
    newUsers: 'New Users (7d)',
    averageResponse: 'Average response (ms)',
    dailyActive: 'Daily Active Users',
    weeklyActive: 'Weekly Active Users',
    newUsers7d: 'New Users (7d)',
    documentsByType: 'Documents by Type',
    queriesByDepartment: 'Queries by Department',
    documentsByVisibility: 'Documents by Visibility',
    topUsersByQueries: 'Top Users by Queries',
    averageRating: 'Average Rating',
    conversationLengths: 'Conversation Lengths',
    loadingStats: 'Loading stats...',
    noStats: 'No statistics available.',
    queries: 'Queries',
    users: 'Users',
    documents: 'Documents',
    conversations: 'Conversations',
    totalQueriesLabel: 'Total queries',
    dau: 'Daily Active Users',
    wau: 'Weekly Active Users',
    contentRisk: 'Content Risk Documents',
    queriesLabel: 'Queries',
    avgMs: 'Avg ms',
    lastActive: 'Last Active',
    noUserStats: 'No user statistics available yet.',
    noSystemStats: 'No system statistics available yet.',
    noUsersMatch: 'No users match this search.',
    fallback: 'Fallback %',
    deleteConversationTitle: 'Delete conversation',
    deleteConversationBody: 'This will permanently remove this conversation and its messages.',
    deleteSelectedConversationsTitle: 'Delete selected conversations',
    deleteSelectedConversationsBody: 'This will permanently remove the selected conversations and all their messages.',
    askQuestion: 'Ask your question...',
    model: 'Model',
    summaryDetails: 'Summary Details',
    saved: 'Saved',
    selectSummary: 'Select a summary from the list to view details.',
    loadingSummary: 'Loading summary...',
    noSummaries: 'No summaries found.',
    summarizeAction: 'Summarize',
    deleteFileTitle: 'Delete file',
    deleteFileBody: 'This will permanently remove this file and its indexed vectors.',
    deleteAll: 'Delete all',
    deleteSummaryTitle: 'Delete summary',
    deleteSummaryBody: 'This will permanently remove this summary.',
    summariesBulkDeleteTitle: 'Delete selected summaries',
    summariesBulkDeleteBody: 'This will permanently remove the selected summaries.'
  },
  ar: {
    chat: 'المحادثة',
    navChat: 'المحادثة',
    navStats: 'الإحصاءات',
    navSummaries: 'الملخصات',
    navAdminFiles: 'إدارة الملفات ',
    navAdminUsers: 'إدارة المستخدمين',
    navLogin: 'تسجيل الدخول',
    navSignup: 'تسجيل',
    navFiles: 'الملفات',
    logout: 'تسجيل الخروج',
    docType: 'نوع المستند',
    search: 'بحث...',
    loading: 'جاري التحميل...',
    previous: 'السابق',
    next: 'التالي',
    page: 'الصفحة',
    yes: 'نعم',
    no: 'لا',
    id: 'المعرّف',
    name: 'الاسم',
    size: 'الحجم',
    visibility: 'الصلاحية',
    actions: 'إجراءات',
    all: 'عام',
    private: 'خاص',
    public: 'عام',
    global: 'عام',
    asset: 'مستند',
    conversation: 'محادثة',
    department: 'القسم',
    created: 'تاريخ الإنشاء',
    lastLogin: 'آخر دخول',
    total: 'الإجمالي',
    goToChat: 'الانتقال للمحادثة',
    bytes: 'بايت',
    close: 'إغلاق',
    edit: 'تعديل',
    dismiss: 'إغلاق',
    of: 'من',
    source: 'مصدر',
    excerpt: 'مقتطف',
    friendlyServerIssue: 'نقوم بترتيب الأمور في الخلفية. يرجى المحاولة مرة أخرى بعد قليل.',
    resources: 'المصادر',
    allFiles: 'كل الملفات',
    filesSelected: 'ملف/ملفات محددة',
    noFilesForType: 'لا توجد ملفات لهذا النوع.',
    searchFiles: 'ابحث عن ملف...',
    startChat: 'ابدأ محادثة جديدة للمتابعة.',
    helpful: 'مفيد👍',
    notHelpful: 'غير مفيد👎',
    upload: 'رفع ملف',
    showSummary: 'إظهار لوحة الملخص',
    hideSummary: 'إخفاء لوحة الملخص',
    clear: 'مسح',
    noConversations: 'لا توجد محادثات بعد. ابدأ محادثة جديدة.',
    conversationTitle: 'محادثة',
    newChat: 'محادثة جديدة',
    rename: 'إعادة تسمية',
    delete: 'حذف',
    send: 'إرسال',
    loginTitle: 'تسجيل الدخول - المساعد العسكري',
    loginSubtitle: 'أدخل بيانات الاعتماد للاستمرار.',
    username: 'اسم المستخدم',
    password: 'كلمة المرور',
    login: 'تسجيل الدخول',
    signingIn: 'جاري تسجيل الدخول...',
    invalidCredentials: 'بيانات الدخول غير صحيحة',
    signupTitle: 'إنشاء حساب',
    signupSubtitle: 'سيتم إنشاء حساب جديد على النظام.',
    signupSubmit: 'تسجيل',
    backToLogin: 'العودة لتسجيل الدخول',
    signupValidationUserPass: 'يرجى إدخال اسم المستخدم وكلمة المرور.',
    signupValidationUserLen: 'يجب أن يكون اسم المستخدم 3 أحرف على الأقل.',
    signupValidationPassLen: 'يجب أن تكون كلمة المرور 6 أحرف على الأقل.',
    signupSuccess: 'تم إنشاء المستخدم. يمكنك تسجيل الدخول الآن.',
    signupFailed: 'فشل التسجيل',
    signupUserExists: 'اسم المستخدم هذا مستخدم بالفعل. يرجى اختيار اسم آخر.',
    adminUsers: 'إدارة المستخدمين',
    createUser: 'إنشاء مستخدم',
    role: 'الدور',
    create: 'إنشاء',
    loadingUsers: 'جاري تحميل المستخدمين...',
    noUsers: 'لا يوجد مستخدمون.',
    searchUsers: 'ابحث عن مستخدم...',
    searchUsersPlaceholder: 'ابحث باسم المستخدم أو القسم...',
    resetPassword: 'إعادة تعيين كلمة المرور',
    save: 'حفظ',
    cancel: 'إلغاء',
    admin: 'مدير',
    user: 'مستخدم',
    totalUsersLabel: 'إجمالي المستخدمين',
    adminFiles: 'إدارة الملفات',
    searchAssets: 'ابحث بالاسم أو النوع...',
    searchAssetsPlaceholder: 'ابحث بالاسم أو النوع...',
    refresh: 'تحديث',
    deleteSelected: 'حذف المحدد',
    loadingAssets: 'جاري تحميل الملفات...',
    noAssets: 'لا توجد ملفات.',
    bulkDeleteTitle: 'حذف العناصر المحددة',
    bulkDeleteConfirm: 'سيتم حذف العناصر المحددة نهائياً.',
    totalAssetsLabel: 'إجمالي الملفات',
    uploadTitle: 'رفع وفهرسة الملفات',
    selectFiles: 'اختر الملفات',
    docTypePlaceholder: 'أو أدخل نوع مستند جديد...',
    docTypePlaceholderRequired: 'أدخل نوع المستند (مطلوب)...',
    docTypeRequired: 'نوع المستند مطلوب.',
    visibilityLabel: 'الصلاحية',
    privateOnlyYou: 'خاص (لك فقط)',
    departmentVisibility: 'القسم',
    globalVisibility: 'عام',
    isPrivate: 'ملف خاص',
    departmentLabel: 'القسم',
    chooseExisting: 'استخدام الموجود',
    enterNew: 'إدخال جديد',
    searchDepartmentsPlaceholder: 'اكتب للبحث عن الأقسام...',
    newDepartmentPlaceholder: 'أدخل اسم قسم جديد...',
    submitUpload: 'رفع',
    cancelUpload: 'إلغاء',
    uploading: 'جاري الرفع...',
    processingIndexing: 'جاري المعالجة والفهرسة...',
    chunks: 'عُقد',
    noFilesSelected: 'لم يتم اختيار ملفات',
    uploadSuccessSingle: 'تم رفع ومعالجة وفهرسة الملف بنجاح.',
    uploadSuccessMulti: 'تم رفع وفهرسة الملفات بنجاح.',
    uploadFailed: 'فشل الرفع',
    selectDocTypeFirst: 'يرجى اختيار نوع مستند قبل البدء بالمحادثة.',
    summaries: 'الملخصات',
    generateSummary: 'إنشاء ملخص',
    summaryFocusPlaceholder: 'مثال: المسؤوليات، المخاطر، أو نظرة عامة.',
    summaryFocusLabel: 'موضوع الملخص (اختياري)',
    summaryDepthLabel: 'درجة التفصيل',
    summaryDepthShort: 'ملخص قصير',
    summaryDepthNormal: 'ملخص عادي',
    summaryDepthDetailed: 'ملخص مفصل',
    documentSummary: 'ملخص المستند',
    file: 'ملف',
    noFilesAvailable: 'لا توجد ملفات متاحة',
    selectFile: 'اختر ملفاً',
    summarize: 'تلخيص',
    summarizing: 'جاري التلخيص...',
    generatingSummary: 'جارٍ إنشاء الملخص...',
    summaryWillAppear: 'سيظهر الملخص هنا.',
    summaryFailed: 'فشل إنشاء الملخص.',
    confirmDeleteSummary: 'سيتم حذف هذا الملخص نهائياً.',
    stats: 'الإحصاءات',
    myStats: 'إحصائياتي',
    usersTab: 'المستخدمون',
    systemTab: 'النظام',
    totalQueries: 'إجمالي الاستعلامات',
    totalDocuments: 'الوثائق',
    totalUsers: 'المستخدمون',
    totalConversations: 'المحادثات',
    newUsers: 'المستخدمون الجدد (٧ أيام)',
    averageResponse: 'متوسط الاستجابة (مللي ثانية)',
    dailyActive: 'المستخدمون النشطون يومياً',
    weeklyActive: 'المستخدمون النشطون أسبوعياً',
    newUsers7d: 'المستخدمون الجدد (٧ أيام)',
    documentsByType: 'الوثائق حسب النوع',
    queriesByDepartment: 'الاستعلامات حسب القسم',
    documentsByVisibility: 'الوثائق حسب الصلاحية',
    topUsersByQueries: 'أكثر المستخدمين استعلاماً',
    averageRating: 'متوسط التقييم',
    conversationLengths: 'أطوال المحادثات',
    loadingStats: 'جاري تحميل الإحصاءات...',
    noStats: 'لا توجد إحصاءات متاحة.',
    queries: 'الاستعلامات',
    users: 'المستخدمون',
    documents: 'الوثائق',
    conversations: 'المحادثات',
    totalQueriesLabel: 'إجمالي الاستعلامات',
    dau: 'المستخدمون النشطون يومياً',
    wau: 'المستخدمون النشطون أسبوعياً',
    contentRisk: 'وثائق ذات مخاطر محتوى',
    queriesLabel: 'الاستعلامات',
    avgMs: 'متوسط مللي ثانية',
    lastActive: 'آخر نشاط',
    noUserStats: 'لا توجد إحصاءات مستخدم حتى الآن.',
    noSystemStats: 'لا توجد إحصاءات نظام حتى الآن.',
    noUsersMatch: 'لا يوجد مستخدمون مطابقون لهذا البحث.',
    fallback: 'نسبة البديل',
    deleteConversationTitle: 'حذف المحادثة',
    deleteConversationBody: 'سيتم حذف هذه المحادثة وجميع رسائلها نهائياً.',
    deleteSelectedConversationsTitle: 'حذف المحادثات المحددة',
    deleteSelectedConversationsBody: 'سيتم حذف المحادثات المحددة وكل رسائلها نهائياً.',
    askQuestion: 'اكتب سؤالك...',
    model: 'النموذج',
    summaryDetails: 'تفاصيل الملخص',
    saved: 'تم الحفظ',
    selectSummary: 'اختر ملخصاً من القائمة لعرض التفاصيل.',
    loadingSummary: 'جاري تحميل الملخص...',
    noSummaries: 'لا توجد ملخصات.',
    summarizeAction: 'تلخيص',
    deleteFileTitle: 'حذف الملف',
    deleteFileBody: 'سيتم حذف هذا الملف وفهارسه نهائياً.',
    deleteAll: 'حذف الكل',
    deleteSummaryTitle: 'حذف الملخص',
    deleteSummaryBody: 'سيتم حذف هذا الملخص نهائياً.',
    summariesBulkDeleteTitle: 'حذف الملخصات المحددة',
    summariesBulkDeleteBody: 'سيتم حذف الملخصات المحددة نهائياً.'
  }
};

export const t = (lang: UILanguage, key: Key): string => {
  const dict = STRINGS[lang] || STRINGS.en;
  return dict[key] || STRINGS.en[key] || '';
};
