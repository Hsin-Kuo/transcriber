<template>
  <div class="settings-container">
    <!-- 使用者資訊顯示面板 -->
    <div class="user-display-wrapper">
      <!-- 顯示面板 -->
      <div class="user-display-panel">
        <span class="panel-label">{{ $t('userSettings.account') }}</span>
        <div class="display-row">
          <span class="display-value">{{ authStore.user?.email || '---' }}</span>
        </div>
        <span class="panel-label">{{ $t('userSettings.language') }}</span>
        <div class="display-row">
          <span class="display-value">{{ currentLanguageLabel }}</span>
        </div>
        <div class="display-row-inline">
          <div class="display-col">
            <span class="panel-label">{{ $t('userSettings.timezone') }}</span>
            <div class="display-row">
              <span class="display-value">{{ getTimezoneShort(currentTimezone) }}</span>
            </div>
          </div>
          <div class="display-col">
            <span class="panel-label">{{ $t('userSettings.theme') }}</span>
            <div class="display-row">
              <span class="display-value theme-icons">
                <!-- 太陽 -->
                <svg :class="{ active: currentTheme === 'light' }" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="5"></circle>
                  <line x1="12" y1="1" x2="12" y2="3"></line>
                  <line x1="12" y1="21" x2="12" y2="23"></line>
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                  <line x1="1" y1="12" x2="3" y2="12"></line>
                  <line x1="21" y1="12" x2="23" y2="12"></line>
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                </svg>
                <!-- 月亮 -->
                <svg :class="{ active: currentTheme === 'dark' }" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                </svg>
              </span>
            </div>
          </div>
        </div>

        <!-- 時長 -->
        <div class="usage-label-row" style="margin-top: 8px;">
          <span class="panel-label">{{ $t('userSettings.duration') }}</span>
          <span class="display-value usage-value"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px; vertical-align: middle;"><circle cx="12" cy="14" r="8"></circle><polyline points="12 10 12 14 15 16"></polyline><line x1="12" y1="2" x2="12" y2="6"></line><line x1="8" y1="2" x2="16" y2="2"></line></svg>{{ Math.round(authStore.usage?.duration_minutes || 0) }}/{{ authStore.quota?.max_duration_minutes || 0 }}min</span>
        </div>
        <div class="display-bar">
          <span class="bar-fill" :style="{ width: (authStore.quotaPercentage?.duration || 0) + '%' }"></span>
        </div>

        <!-- AI 摘要 -->
        <div class="usage-label-row">
          <span class="panel-label">{{ $t('userSettings.aiSummary') }}</span>
          <span class="display-value usage-value"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style="margin-right: 4px; vertical-align: middle;"><path d="M12 1L14.5 9.5L23 12L14.5 14.5L12 23L9.5 14.5L1 12L9.5 9.5Z" /></svg>{{ authStore.usage?.ai_summaries || 0 }}/{{ authStore.quota?.max_ai_summaries || 0 }}</span>
        </div>
        <div class="display-bar">
          <span class="bar-fill" :style="{ width: aiSummaryPercentage + '%' }"></span>
        </div>
      </div>

      <!-- 方案指標 -->
      <div class="plan-indicator-wrapper">
        <svg class="corner-screw corner-tl" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="0.8"/><rect x="4" y="9" width="12" height="2" rx="0.5" fill="currentColor"/></svg>
        <svg class="corner-screw corner-tr" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="0.8"/><rect x="4" y="9" width="12" height="2" rx="0.5" fill="currentColor"/></svg>
        <svg class="corner-screw corner-bl" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="0.8"/><rect x="4" y="9" width="12" height="2" rx="0.5" fill="currentColor"/></svg>
        <svg class="corner-screw corner-br" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="0.8"/><rect x="4" y="9" width="12" height="2" rx="0.5" fill="currentColor"/></svg>
        <span class="plan-indicator-title">{{ $t('userSettings.plan') }}</span>
        <div class="plan-indicator">
          <div class="plan-indicator-pointer-track">
            <svg class="plan-pointer" :class="'point-to-' + previewTier" viewBox="0 0 18 60" xmlns="http://www.w3.org/2000/svg">
              <path d="M9,0 L16,18 Q18,22 18,26 L18,56 Q18,60 14,60 L4,60 Q0,60 0,56 L0,26 Q0,22 2,18 Z" fill="currentColor" />
            </svg>
          </div>
          <div class="plan-indicator-lines">
            <div class="plan-indicator-item" :class="{ active: previewTier === 'free' }" @click="previewTier = 'free'">
              <span class="plan-arc-wrapper"><svg class="plan-arc plan-arc-long" viewBox="0 0 70 18"><path d="M0,18 Q14,7 28,7 L70,7" fill="none" stroke="currentColor" stroke-width="1"/></svg></span>
              <span class="plan-indicator-dot"></span><span class="plan-indicator-label">FREE</span>
            </div>
            <div class="plan-indicator-item" :class="{ active: previewTier === 'basic' }" @click="previewTier = 'basic'">
              <span class="plan-arc-wrapper"><svg class="plan-arc plan-arc-short" viewBox="0 0 50 14"><path d="M0,12 Q8,7 16,7 L50,7" fill="none" stroke="currentColor" stroke-width="1"/></svg></span>
              <span class="plan-indicator-dot"></span><span class="plan-indicator-label">BASIC</span>
            </div>
            <div class="plan-indicator-item" :class="{ active: previewTier === 'pro' }" @click="previewTier = 'pro'">
              <span class="plan-arc-wrapper"><svg class="plan-arc plan-arc-short" viewBox="0 0 50 14"><path d="M0,2 Q8,7 16,7 L50,7" fill="none" stroke="currentColor" stroke-width="1"/></svg></span>
              <span class="plan-indicator-dot"></span><span class="plan-indicator-label">PRO</span>
            </div>
            <div class="plan-indicator-item" :class="{ active: previewTier === 'enterprise' }" @click="previewTier = 'enterprise'">
              <span class="plan-arc-wrapper"><svg class="plan-arc plan-arc-long" viewBox="0 0 70 18"><path d="M0,0 Q14,11 28,11 L70,11" fill="none" stroke="currentColor" stroke-width="1"/></svg></span>
              <span class="plan-indicator-dot"></span><span class="plan-indicator-label">ENT</span>
            </div>
          </div>
        </div>
        <div class="plan-indicator-actions">
          <button class="plan-btn plan-btn-outline" @click="showPlanPanel = true">{{ $t('userSettings.showPlan') }}</button>
          <button class="plan-btn plan-btn-primary" @click="showPlanPanel = true"><svg class="plan-btn-icon" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg"><path d="M8,1 A7,7 0 1,0 8,15 A7,7 0 1,0 8,1 Z M8,6.5 A1.5,1.5 0 1,1 8,9.5 A1.5,1.5 0 1,1 8,6.5 Z M7.5,1 L8.5,1 L8.5,5.5 L7.5,5.5 Z" fill="currentColor" fill-rule="evenodd"/></svg>{{ $t('userSettings.upgrade') }}</button>
        </div>
      </div>
    </div>

    <div class="settings-grid">
      <!-- 帳戶安全 -->
      <div class="card security-card" :class="{ expanded: securityExpanded }" @click="!securityExpanded && (securityExpanded = true)">
        <h2 class="card-toggle" @click.stop="securityExpanded = !securityExpanded">
          <span class="card-title-left"><svg class="card-icon" :class="{ active: securityExpanded }" width="33" height="27" viewBox="0 0 28 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 10l16-8 10 8v12a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2z"></path></svg>{{ $t('userSettings.security') }}</span>
          <svg class="toggle-arrow" :class="{ expanded: securityExpanded }" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </h2>
        <p class="card-subtitle" :class="{ hidden: securityExpanded }">{{ $t('userSettings.securityDesc') }}</p>
        <div class="card-body" :class="{ expanded: securityExpanded }">

        <!-- 密碼設定 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.password') }}</span>
          <div v-if="authStore.hasPassword">
            <button class="change-password-btn" @click="showPasswordModal = true">
              {{ $t('userSettings.changePassword') }}
            </button>
          </div>
          <div v-else>
            <button class="change-password-btn" @click="showSetPasswordModal = true">
              {{ $t('userSettings.setPassword') }}
            </button>
          </div>
        </div>

        <!-- Google 綁定 -->
        <div v-if="googleClientId" class="setting-item google-setting">
          <div class="setting-left">
            <span class="setting-label">{{ $t('userSettings.googleAccount') }}</span>
            <span v-if="authStore.hasGoogle" class="connected-status">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              {{ $t('userSettings.connected') }}
            </span>
          </div>
          <div class="setting-right">
            <!-- 未綁定：顯示綁定按鈕 -->
            <div v-if="!authStore.hasGoogle" class="google-bind-wrapper">
              <GoogleSignInButton
                :key="'google-bind-' + locale"
                :client-id="googleClientId"
                button-text="signin_with"
                size="medium"
                :width="200"
                @success="handleGoogleBindSuccess"
                @error="handleGoogleBindError"
              />
            </div>
            <!-- 已綁定：顯示解除綁定按鈕 -->
            <div v-else>
              <button
                class="unbind-btn"
                @click="confirmUnbindGoogle"
                :disabled="googleLoading"
              >
                {{ googleLoading ? $t('userSettings.processing') : $t('userSettings.unbind') }}
              </button>
            </div>
          </div>
        </div>

        <!-- Google 操作訊息 -->
        <div v-if="googleError" class="google-message error">{{ googleError }}</div>
        <div v-if="googleSuccess" class="google-message success">{{ googleSuccess }}</div>

        <!-- 刪除帳號 -->
        <div class="setting-item delete-account-item">
          <span class="setting-label delete-label">{{ $t('userSettings.deleteAccount') }}</span>
          <button class="delete-account-btn" @click="showDeleteAccountModal = true">
            {{ $t('userSettings.deleteAccount') }}
          </button>
        </div>
        </div>
      </div>

      <!-- 介面設定 -->
      <div class="card interface-card" :class="{ expanded: preferencesExpanded }" @click="!preferencesExpanded && (preferencesExpanded = true)">
        <h2 class="card-toggle" @click.stop="preferencesExpanded = !preferencesExpanded">
          <span class="card-title-left"><svg class="card-icon" :class="{ active: preferencesExpanded }" width="50" height="27" viewBox="0 0 28 24" preserveAspectRatio="none" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 10l16-8 10 8v12a2 2 0 0 1-2 2H11v-10H5v10H3a2 2 0 0 1-2-2z"></path></svg><svg class="card-icon-person" width="7" height="14" viewBox="0 0 10 20" fill="var(--main-text)" stroke="none"><path d="M5 1a2.5 2.5 0 0 0-1.8 4.2c-.5.3-.8.8-.8 1.3v2.5l-1 5v.5L.8 20H3l1.5-4h1l.8 4h1.8l-.1-5.5v-.5l-1-5V6.5c0-.5-.3-1-.8-1.3A2.5 2.5 0 0 0 5 1z"/></svg>{{ $t('userSettings.interface') }}</span>
          <svg class="toggle-arrow" :class="{ expanded: preferencesExpanded }" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </h2>
        <p class="card-subtitle" :class="{ hidden: preferencesExpanded }">{{ $t('userSettings.preferencesDesc') }}</p>
        <div class="card-body" :class="{ expanded: preferencesExpanded }">

        <!-- 語言 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.language') }}</span>
          <div class="custom-select" :class="{ open: languageDropdownOpen }">
            <div class="select-trigger" @click="toggleLanguageDropdown">
              <span>{{ currentLanguageLabel }}</span>
              <svg class="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <div class="select-dropdown">
              <div
                v-for="lang in availableLanguages"
                :key="lang.code"
                class="select-option"
                :class="{ active: currentLanguage === lang.code }"
                @click="selectLanguage(lang.code)"
              >
                {{ lang.name }}
              </div>
            </div>
          </div>
        </div>

        <!-- 時區 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.timezone') }}</span>
          <div class="custom-select" :class="{ open: timezoneDropdownOpen }">
            <div class="select-trigger" @click="toggleTimezoneDropdown">
              <span>{{ currentTimezoneLabel }}</span>
              <svg class="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <div class="select-dropdown">
              <div
                v-for="tz in availableTimezones"
                :key="tz.code"
                class="select-option"
                :class="{ active: currentTimezone === tz.code }"
                @click="selectTimezone(tz.code)"
              >
                {{ tz.name }}
              </div>
            </div>
          </div>
        </div>

        <!-- 色調 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.theme') }}</span>
          <div class="theme-toggle">
            <svg class="theme-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="5"></circle>
              <line x1="12" y1="1" x2="12" y2="3"></line>
              <line x1="12" y1="21" x2="12" y2="23"></line>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
              <line x1="1" y1="12" x2="3" y2="12"></line>
              <line x1="21" y1="12" x2="23" y2="12"></line>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
            </svg>
            <label class="toggle-switch" :class="{ active: currentTheme === 'dark' }">
              <input type="checkbox" :checked="currentTheme === 'dark'" @change="currentTheme = $event.target.checked ? 'dark' : 'light'; changeTheme()" />
              <span class="toggle-slider"></span>
            </label>
            <svg class="theme-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
          </div>
        </div>

        <!-- AI 摘要展開 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.summaryExpand') }}</span>
          <div class="custom-select" :class="{ open: summaryExpandDropdownOpen }">
            <div class="select-trigger" @click="toggleSummaryExpandDropdown">
              <span>{{ currentSummaryExpandLabel }}</span>
              <svg class="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <div class="select-dropdown">
              <div
                class="select-option"
                :class="{ active: summaryExpandMode === 'always-open' }"
                @click="selectSummaryExpandMode('always-open')"
              >
                {{ $t('userSettings.summaryAlwaysOpen') }}
              </div>
              <div
                class="select-option"
                :class="{ active: summaryExpandMode === 'always-collapsed' }"
                @click="selectSummaryExpandMode('always-collapsed')"
              >
                {{ $t('userSettings.summaryAlwaysCollapsed') }}
              </div>
              <div
                class="select-option"
                :class="{ active: summaryExpandMode === 'follow-last' }"
                @click="selectSummaryExpandMode('follow-last')"
              >
                {{ $t('userSettings.summaryFollowLast') }}
              </div>
            </div>
          </div>
        </div>
        </div>
      </div>

      <!-- Support -->
      <div class="card support-card" :class="{ expanded: supportExpanded }" @click="!supportExpanded && (supportExpanded = true)">
        <h2 class="card-toggle" @click.stop="supportExpanded = !supportExpanded">
          <span class="card-title-left"><svg class="card-icon" :class="{ active: supportExpanded }" width="22" height="27" viewBox="0 0 20 26" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 1l17 5v18H2a1 1 0 0 1-1-1z"/></svg><svg class="card-icon-person" width="7" height="12" viewBox="0 0 10 20" fill="var(--main-primary)" stroke="none"><path d="M5 1a2.5 2.5 0 0 0-1.8 4.2c-.5.3-.8.8-.8 1.3v2.5l-1 5v.5L2.2 20H4l.5-4h1l.3 2H7.8l-.2-3.5v-.5l-1-5V6.5c0-.5-.3-1-.8-1.3A2.5 2.5 0 0 0 5 1z"/></svg><svg class="card-icon-person card-icon-person-second" width="7" height="14" viewBox="0 0 10 20" fill="var(--main-primary)" stroke="none"><path d="M5 1a2.5 2.5 0 0 0-1.8 4.2c-.5.3-.8.8-.8 1.3v2.5l-1 5v.5L.8 20H3l1.5-4h1l.8 4h1.8l-.1-5.5v-.5l-1-5V6.5c0-.5-.3-1-.8-1.3A2.5 2.5 0 0 0 5 1z"/><path d="M2.4 7.5L-3 10v1.5L2.4 9z"/></svg>{{ $t('userSettings.support') }}</span>
          <svg class="toggle-arrow" :class="{ expanded: supportExpanded }" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </h2>
        <p class="card-subtitle" :class="{ hidden: supportExpanded }">{{ $t('userSettings.supportDesc') }}</p>
        <div class="card-body" :class="{ expanded: supportExpanded }">
          <a class="setting-item link-item" href="#" target="_blank">
            <span class="setting-label">{{ $t('userSettings.helpCenter') }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
          <a class="setting-item link-item" href="#" target="_blank">
            <span class="setting-label">{{ $t('userSettings.faq') }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
          <a class="setting-item link-item" href="#" target="_blank">
            <span class="setting-label">{{ $t('userSettings.contactUs') }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
        </div>
      </div>

      <!-- Documents -->
      <div class="card documents-card" :class="{ expanded: documentsExpanded }" @click="!documentsExpanded && (documentsExpanded = true)">
        <h2 class="card-toggle" @click.stop="documentsExpanded = !documentsExpanded">
          <span class="card-title-left"><svg class="card-icon" :class="{ active: documentsExpanded }" width="50" height="27" viewBox="0 0 28 24" preserveAspectRatio="none" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 8L27 2V22a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2z M3 11h5v19H3z M20 8h7v10h-7z" fill-rule="evenodd"></path></svg>{{ $t('userSettings.documents') }}</span>
          <svg class="toggle-arrow" :class="{ expanded: documentsExpanded }" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </h2>
        <p class="card-subtitle" :class="{ hidden: documentsExpanded }">{{ $t('userSettings.documentsDesc') }}</p>
        <div class="card-body" :class="{ expanded: documentsExpanded }">
          <a class="setting-item link-item" href="#" target="_blank">
            <span class="setting-label">{{ $t('userSettings.privacyPolicy') }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
          <a class="setting-item link-item" href="#" target="_blank">
            <span class="setting-label">{{ $t('userSettings.termsOfService') }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
        </div>
      </div>

      <!-- Team -->
      <div class="card team-card" :class="{ expanded: teamExpanded }" @click="!teamExpanded && (teamExpanded = true)">
        <h2 class="card-toggle" @click.stop="teamExpanded = !teamExpanded">
          <span class="card-title-left"><svg class="card-icon-person card-icon-person-left" width="7" height="14" viewBox="0 0 10 20" fill="var(--main-text)" stroke="none"><path d="M5 1a2.5 2.5 0 0 0-1.8 4.2c-.5.3-.8.8-.8 1.3v2.5l-1 5v.5L.8 20H3l1.5-4h1l.8 4h1.8l-.1-5.5v-.5l-1-5V6.5c0-.5-.3-1-.8-1.3A2.5 2.5 0 0 0 5 1z"/></svg><svg class="card-icon-hands" width="6" height="6" viewBox="0 0 10 10" fill="none" stroke="var(--main-text)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 2 5 7 9 2"></polyline></svg><svg class="card-icon-person card-icon-person-left-second" width="7" height="14" viewBox="0 0 10 20" fill="var(--main-text)" stroke="none"><path d="M5 1a2.5 2.5 0 0 0-1.8 4.2c-.5.3-.8.8-.8 1.3v2.5l-1 5v.5L.8 20H3l1.5-4h1l.8 4h1.8l-.1-5.5v-.5l-1-5V6.5c0-.5-.3-1-.8-1.3A2.5 2.5 0 0 0 5 1z"/></svg><svg class="card-icon" :class="{ active: teamExpanded }" width="44" height="33" viewBox="0 0 28 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3h16l10-1v20H18V12H2v10H1z"></path></svg>{{ $t('userSettings.team') }}</span>
          <svg class="toggle-arrow" :class="{ expanded: teamExpanded }" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </h2>
        <p class="card-subtitle" :class="{ hidden: teamExpanded }">{{ $t('userSettings.teamDesc') }}</p>
        <div class="card-body" :class="{ expanded: teamExpanded }">
          <a class="setting-item link-item" href="#" target="_blank">
            <span class="setting-label">{{ $t('userSettings.aboutUs') }}</span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
          </a>
        </div>
      </div>
    </div>

    <!-- 更改密碼 Modal -->
    <div v-if="showPasswordModal" class="modal-overlay" @click.self="closePasswordModal">
      <div class="modal">
        <h3>{{ $t('userSettings.changePassword') }}</h3>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ $t('userSettings.currentPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="passwordForm.currentPassword"
                :type="showCurrentPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.currentPasswordPlaceholder')"
              />
              <button type="button" class="password-toggle" @click="showCurrentPassword = !showCurrentPassword" tabindex="-1">
                <svg v-if="showCurrentPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.newPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="passwordForm.newPassword"
                :type="showNewPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.newPasswordPlaceholder')"
                @input="validateNewPassword"
              />
              <button type="button" class="password-toggle" @click="showNewPassword = !showNewPassword" tabindex="-1">
                <svg v-if="showNewPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
            <div v-if="passwordForm.newPassword" class="password-requirements">
              <div class="requirement" :class="{ met: newPasswordChecks.length }">
                {{ newPasswordChecks.length ? '✓' : '○' }} {{ $t('userSettings.reqLength') }}
              </div>
              <div class="requirement" :class="{ met: newPasswordChecks.hasUpper }">
                {{ newPasswordChecks.hasUpper ? '✓' : '○' }} {{ $t('userSettings.reqUppercase') }}
              </div>
              <div class="requirement" :class="{ met: newPasswordChecks.hasLower }">
                {{ newPasswordChecks.hasLower ? '✓' : '○' }} {{ $t('userSettings.reqLowercase') }}
              </div>
              <div class="requirement" :class="{ met: newPasswordChecks.hasNumber }">
                {{ newPasswordChecks.hasNumber ? '✓' : '○' }} {{ $t('userSettings.reqNumber') }}
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.confirmPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="passwordForm.confirmPassword"
                :type="showConfirmPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.confirmPasswordPlaceholder')"
              />
              <button type="button" class="password-toggle" @click="showConfirmPassword = !showConfirmPassword" tabindex="-1">
                <svg v-if="showConfirmPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>
          <p v-if="passwordError" class="error-text">{{ passwordError }}</p>
          <p v-if="passwordSuccess" class="success-text">{{ passwordSuccess }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closePasswordModal" class="btn-cancel">{{ $t('userSettings.cancel') }}</button>
          <button @click="changePassword" class="btn-confirm" :disabled="isChangingPassword">
            {{ isChangingPassword ? $t('userSettings.changing') : $t('userSettings.confirm') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 刪除帳號 Modal -->
    <div v-if="showDeleteAccountModal" class="modal-overlay" @click.self="closeDeleteAccountModal">
      <div class="modal delete-modal">
        <h3 class="delete-modal-title">{{ $t('userSettings.deleteAccount') }}</h3>
        <div class="modal-body">
          <p class="delete-description">{{ $t('userSettings.deleteAccountDescription') }}</p>
          <ul class="delete-items">
            <li>{{ $t('userSettings.deleteAccountItem1') }}</li>
            <li>{{ $t('userSettings.deleteAccountItem2') }}</li>
            <li>{{ $t('userSettings.deleteAccountItem3') }}</li>
          </ul>
          <p class="delete-warning">{{ $t('userSettings.deleteAccountWarning') }}</p>

          <div class="form-group">
            <label>{{ $t('userSettings.deleteAccountConfirmLabel') }}</label>
            <input
              v-model="deleteAccountForm.confirmation"
              type="email"
              class="form-input"
              :placeholder="authStore.user?.email"
            />
          </div>

          <div v-if="authStore.hasPassword" class="form-group">
            <label>{{ $t('userSettings.deleteAccountPasswordLabel') }}</label>
            <input
              v-model="deleteAccountForm.password"
              type="password"
              class="form-input"
              :placeholder="$t('userSettings.deleteAccountPasswordPlaceholder')"
            />
          </div>

          <p v-if="deleteAccountError" class="error-text">{{ deleteAccountError }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closeDeleteAccountModal" class="btn-cancel">{{ $t('userSettings.cancel') }}</button>
          <button @click="confirmDeleteAccount" class="btn-delete" :disabled="isDeletingAccount">
            {{ isDeletingAccount ? $t('userSettings.deleting') : $t('userSettings.deleteAccount') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 設定密碼 Modal (OAuth 用戶) -->
    <div v-if="showSetPasswordModal" class="modal-overlay" @click.self="closeSetPasswordModal">
      <div class="modal">
        <h3>{{ $t('userSettings.setPassword') }}</h3>
        <p class="modal-description">{{ $t('userSettings.setPasswordDescription') }}</p>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ $t('userSettings.newPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="setPasswordForm.newPassword"
                :type="showSetNewPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.newPasswordPlaceholder')"
                @input="validateSetPassword"
              />
              <button type="button" class="password-toggle" @click="showSetNewPassword = !showSetNewPassword" tabindex="-1">
                <svg v-if="showSetNewPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
            <div v-if="setPasswordForm.newPassword" class="password-requirements">
              <div class="requirement" :class="{ met: setPasswordChecks.length }">
                {{ setPasswordChecks.length ? '✓' : '○' }} {{ $t('userSettings.reqLength') }}
              </div>
              <div class="requirement" :class="{ met: setPasswordChecks.hasUpper }">
                {{ setPasswordChecks.hasUpper ? '✓' : '○' }} {{ $t('userSettings.reqUppercase') }}
              </div>
              <div class="requirement" :class="{ met: setPasswordChecks.hasLower }">
                {{ setPasswordChecks.hasLower ? '✓' : '○' }} {{ $t('userSettings.reqLowercase') }}
              </div>
              <div class="requirement" :class="{ met: setPasswordChecks.hasNumber }">
                {{ setPasswordChecks.hasNumber ? '✓' : '○' }} {{ $t('userSettings.reqNumber') }}
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.confirmPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="setPasswordForm.confirmPassword"
                :type="showSetConfirmPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.confirmPasswordPlaceholder')"
              />
              <button type="button" class="password-toggle" @click="showSetConfirmPassword = !showSetConfirmPassword" tabindex="-1">
                <svg v-if="showSetConfirmPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>
          <p v-if="setPasswordError" class="error-text">{{ setPasswordError }}</p>
          <p v-if="setPasswordSuccess" class="success-text">{{ setPasswordSuccess }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closeSetPasswordModal" class="btn-cancel">{{ $t('userSettings.cancel') }}</button>
          <button @click="setPassword" class="btn-confirm" :disabled="isSettingPassword">
            {{ isSettingPassword ? $t('userSettings.setting') : $t('userSettings.confirm') }}
          </button>
        </div>
      </div>
    </div>
    <PlanPanel v-model="showPlanPanel" :current-tier="currentTier" />
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import api from '../utils/api'
import { detectTimezone, detectTheme } from '../utils/defaults'
import GoogleSignInButton from '../components/GoogleSignInButton.vue'
import PlanPanel from '../components/PlanPanel.vue'

const router = useRouter()
const authStore = useAuthStore()
const { t: $t, locale } = useI18n()

// Google OAuth Client ID
const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

// 更改密碼相關狀態
const showPasswordModal = ref(false)
const isChangingPassword = ref(false)
const passwordError = ref('')
const passwordSuccess = ref('')
const showCurrentPassword = ref(false)
const showNewPassword = ref(false)
const showConfirmPassword = ref(false)
const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const newPasswordChecks = ref({
  length: false,
  hasUpper: false,
  hasLower: false,
  hasNumber: false
})

// Plan panel
const showPlanPanel = ref(false)

// 卡片展開狀態
const securityExpanded = ref(false)
const preferencesExpanded = ref(false)
const supportExpanded = ref(false)
const documentsExpanded = ref(false)
const teamExpanded = ref(false)

// Google 綁定相關狀態
const googleLoading = ref(false)
const googleError = ref('')
const googleSuccess = ref('')

// 設定密碼 Modal（給 OAuth 用戶使用）
const showSetPasswordModal = ref(false)
const setPasswordForm = ref({
  newPassword: '',
  confirmPassword: ''
})
const setPasswordError = ref('')
const setPasswordSuccess = ref('')
const isSettingPassword = ref(false)
const showSetNewPassword = ref(false)
const showSetConfirmPassword = ref(false)
const setPasswordChecks = ref({
  length: false,
  hasUpper: false,
  hasLower: false,
  hasNumber: false
})

function validateNewPassword() {
  const pwd = passwordForm.value.newPassword
  newPasswordChecks.value = {
    length: pwd.length >= 8,
    hasUpper: /[A-Z]/.test(pwd),
    hasLower: /[a-z]/.test(pwd),
    hasNumber: /[0-9]/.test(pwd)
  }
}

const isNewPasswordValid = computed(() => {
  return newPasswordChecks.value.length &&
         newPasswordChecks.value.hasUpper &&
         newPasswordChecks.value.hasLower &&
         newPasswordChecks.value.hasNumber
})

// 可用語言列表
const availableLanguages = [
  { code: 'zh-TW', name: '繁體中文' },
  { code: 'en', name: 'English' }
]

// 當前語言（優先 authStore → fallback localStorage/i18n → 預設值）
const currentLanguage = ref(authStore.preferences.language || locale.value)

// 可用時區列表
const availableTimezones = [
  { code: 'Asia/Taipei', name: 'UTC+8 台北' },
  { code: 'Asia/Tokyo', name: 'UTC+9 東京' },
  { code: 'Asia/Shanghai', name: 'UTC+8 上海' },
  { code: 'Asia/Hong_Kong', name: 'UTC+8 香港' },
  { code: 'America/New_York', name: 'UTC-5 紐約' },
  { code: 'America/Los_Angeles', name: 'UTC-8 洛杉磯' },
  { code: 'Europe/London', name: 'UTC+0 倫敦' }
]

// 當前時區（優先 authStore → fallback localStorage → 偵測系統時區）
const currentTimezone = ref(authStore.preferences.timezone || localStorage.getItem('timezone') || detectTimezone())

// 當前色調（優先 authStore → fallback localStorage → 偵測 OS 深色模式）
const currentTheme = ref(authStore.preferences.theme || localStorage.getItem('theme') || detectTheme())

// AI 摘要展開模式（優先 authStore → fallback localStorage → 預設值）
const summaryExpandMode = ref(
  authStore.preferences.summaryExpandMode || localStorage.getItem('summaryExpandMode') || 'follow-last'
)
const summaryExpandDropdownOpen = ref(false)

// 下拉選單狀態
const languageDropdownOpen = ref(false)
const timezoneDropdownOpen = ref(false)

// 當前選項的顯示文字
const currentLanguageLabel = computed(() => {
  const lang = availableLanguages.find(l => l.code === currentLanguage.value)
  return lang ? lang.name : ''
})

const currentTimezoneLabel = computed(() => {
  const tz = availableTimezones.find(t => t.code === currentTimezone.value)
  return tz ? tz.name : ''
})

const currentSummaryExpandLabel = computed(() => {
  const labels = {
    'always-open': $t('userSettings.summaryAlwaysOpen'),
    'always-collapsed': $t('userSettings.summaryAlwaysCollapsed'),
    'follow-last': $t('userSettings.summaryFollowLast')
  }
  return labels[summaryExpandMode.value] || labels['follow-last']
})

// 切換下拉選單
function toggleLanguageDropdown() {
  languageDropdownOpen.value = !languageDropdownOpen.value
  timezoneDropdownOpen.value = false
  summaryExpandDropdownOpen.value = false
}

function toggleTimezoneDropdown() {
  timezoneDropdownOpen.value = !timezoneDropdownOpen.value
  languageDropdownOpen.value = false
  summaryExpandDropdownOpen.value = false
}

function toggleSummaryExpandDropdown() {
  summaryExpandDropdownOpen.value = !summaryExpandDropdownOpen.value
  languageDropdownOpen.value = false
  timezoneDropdownOpen.value = false
}

async function selectSummaryExpandMode(mode) {
  summaryExpandMode.value = mode
  localStorage.setItem('summaryExpandMode', mode)
  summaryExpandDropdownOpen.value = false
  await authStore.updatePreferences({ summaryExpandMode: mode })
}

// 選擇選項
function selectLanguage(code) {
  currentLanguage.value = code
  changeLanguage()
  languageDropdownOpen.value = false
}

function selectTimezone(code) {
  currentTimezone.value = code
  changeTimezone()
  timezoneDropdownOpen.value = false
}

// 點擊外部關閉下拉選單
function handleClickOutside(event) {
  if (!event.target.closest('.custom-select')) {
    languageDropdownOpen.value = false
    timezoneDropdownOpen.value = false
    summaryExpandDropdownOpen.value = false
  }
}

// 當 authStore preferences 更新時，同步本地 ref 和 localStorage
watch(
  () => authStore.preferences,
  (prefs) => {
    if (prefs.summaryExpandMode && prefs.summaryExpandMode !== summaryExpandMode.value) {
      summaryExpandMode.value = prefs.summaryExpandMode
      localStorage.setItem('summaryExpandMode', prefs.summaryExpandMode)
    }
    if (prefs.language && prefs.language !== currentLanguage.value) {
      currentLanguage.value = prefs.language
      locale.value = prefs.language
      localStorage.setItem('locale', prefs.language)
    }
    if (prefs.timezone && prefs.timezone !== currentTimezone.value) {
      currentTimezone.value = prefs.timezone
      localStorage.setItem('timezone', prefs.timezone)
    }
    if (prefs.theme && prefs.theme !== currentTheme.value) {
      currentTheme.value = prefs.theme
      localStorage.setItem('theme', prefs.theme)
      document.documentElement.setAttribute('data-theme', prefs.theme)
    }
  },
  { deep: true }
)

onMounted(() => {
  document.addEventListener('click', handleClickOutside)

  // 如果 localStorage 已有值但後端沒有，首次同步寫入後端
  const prefs = authStore.preferences
  const localSync = {}
  const localMode = localStorage.getItem('summaryExpandMode')
  if (localMode && !prefs.summaryExpandMode) localSync.summaryExpandMode = localMode
  const localLang = localStorage.getItem('locale')
  if (localLang && !prefs.language) localSync.language = localLang
  const localTz = localStorage.getItem('timezone')
  if (localTz && !prefs.timezone) localSync.timezone = localTz
  const localTheme = localStorage.getItem('theme')
  if (localTheme && !prefs.theme) localSync.theme = localTheme

  if (Object.keys(localSync).length > 0) {
    authStore.updatePreferences(localSync)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

// 當前方案層級
const currentTier = computed(() => authStore.quota?.tier || 'free')

// [測試用] 點擊切換指標，不影響後端
const previewTier = ref(currentTier.value)

// AI 摘要使用百分比
const aiSummaryPercentage = computed(() => {
  const used = authStore.usage?.ai_summaries || 0
  const limit = authStore.quota?.max_ai_summaries || 1
  return Math.min((used / limit) * 100, 100)
})


// 切換語言
function changeLanguage() {
  locale.value = currentLanguage.value
  localStorage.setItem('locale', currentLanguage.value)
  authStore.updatePreferences({ language: currentLanguage.value })
}

// 切換時區
function changeTimezone() {
  localStorage.setItem('timezone', currentTimezone.value)
  authStore.updatePreferences({ timezone: currentTimezone.value })
}

// 切換色調
function changeTheme() {
  localStorage.setItem('theme', currentTheme.value)
  document.documentElement.setAttribute('data-theme', currentTheme.value)
  authStore.updatePreferences({ theme: currentTheme.value })
}

// 取得時區簡短顯示
function getTimezoneShort(tzCode) {
  const tz = availableTimezones.find(t => t.code === tzCode)
  if (!tz) return tzCode
  // 從 "UTC+8 台北" 取出 "UTC+8"
  const match = tz.name.match(/UTC[+-]?\d+/)
  return match ? match[0] : tzCode
}

// 關閉密碼對話框
function closePasswordModal() {
  showPasswordModal.value = false
  passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
  passwordError.value = ''
  passwordSuccess.value = ''
  showCurrentPassword.value = false
  showNewPassword.value = false
  showConfirmPassword.value = false
  newPasswordChecks.value = { length: false, hasUpper: false, hasLower: false, hasNumber: false }
}

// 更改密碼
async function changePassword() {
  passwordError.value = ''
  passwordSuccess.value = ''

  // 驗證
  if (!passwordForm.value.currentPassword) {
    passwordError.value = $t('userSettings.errorCurrentPasswordRequired')
    return
  }

  if (!isNewPasswordValid.value) {
    passwordError.value = $t('userSettings.errorPasswordRequirements')
    return
  }

  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    passwordError.value = $t('userSettings.errorPasswordMismatch')
    return
  }

  isChangingPassword.value = true

  try {
    await api.post('/auth/change-password', {
      current_password: passwordForm.value.currentPassword,
      new_password: passwordForm.value.newPassword
    })
    passwordSuccess.value = $t('userSettings.passwordChanged')
    // 2 秒後自動關閉對話框
    setTimeout(() => {
      closePasswordModal()
    }, 2000)
  } catch (err) {
    passwordError.value = err.response?.data?.detail || $t('userSettings.errorChangeFailed')
  } finally {
    isChangingPassword.value = false
  }
}

// Google 綁定成功
async function handleGoogleBindSuccess(credential) {
  googleLoading.value = true
  googleError.value = ''
  googleSuccess.value = ''

  const result = await authStore.bindGoogle(credential)

  if (result.success) {
    googleSuccess.value = $t('userSettings.googleBindSuccess')
    setTimeout(() => {
      googleSuccess.value = ''
    }, 3000)
  } else {
    googleError.value = result.error
  }

  googleLoading.value = false
}

// Google 綁定失敗
function handleGoogleBindError(err) {
  googleError.value = $t('userSettings.googleBindFailed') + ': ' + err
}

// 確認解除 Google 綁定
function confirmUnbindGoogle() {
  // 如果用戶沒有密碼，警告他們
  if (!authStore.hasPassword) {
    if (!confirm($t('userSettings.unbindWarningNoPassword'))) {
      return
    }
  } else {
    if (!confirm($t('userSettings.unbindConfirm'))) {
      return
    }
  }
  unbindGoogle()
}

// 解除 Google 綁定
async function unbindGoogle() {
  googleLoading.value = true
  googleError.value = ''
  googleSuccess.value = ''

  const result = await authStore.unbindGoogle()

  if (result.success) {
    googleSuccess.value = $t('userSettings.googleUnbindSuccess')
    setTimeout(() => {
      googleSuccess.value = ''
    }, 3000)
  } else {
    googleError.value = result.error
  }

  googleLoading.value = false
}

// 驗證設定密碼表單
function validateSetPassword() {
  const pwd = setPasswordForm.value.newPassword
  setPasswordChecks.value = {
    length: pwd.length >= 8,
    hasUpper: /[A-Z]/.test(pwd),
    hasLower: /[a-z]/.test(pwd),
    hasNumber: /[0-9]/.test(pwd)
  }
}

const isSetPasswordValid = computed(() => {
  return setPasswordChecks.value.length &&
         setPasswordChecks.value.hasUpper &&
         setPasswordChecks.value.hasLower &&
         setPasswordChecks.value.hasNumber
})

// 關閉設定密碼對話框
function closeSetPasswordModal() {
  showSetPasswordModal.value = false
  setPasswordForm.value = { newPassword: '', confirmPassword: '' }
  setPasswordError.value = ''
  setPasswordSuccess.value = ''
  showSetNewPassword.value = false
  showSetConfirmPassword.value = false
  setPasswordChecks.value = { length: false, hasUpper: false, hasLower: false, hasNumber: false }
}

// 設定密碼
async function setPassword() {
  setPasswordError.value = ''
  setPasswordSuccess.value = ''

  if (!isSetPasswordValid.value) {
    setPasswordError.value = $t('userSettings.errorPasswordRequirements')
    return
  }

  if (setPasswordForm.value.newPassword !== setPasswordForm.value.confirmPassword) {
    setPasswordError.value = $t('userSettings.errorPasswordMismatch')
    return
  }

  isSettingPassword.value = true

  const result = await authStore.setPassword(setPasswordForm.value.newPassword)

  if (result.success) {
    setPasswordSuccess.value = $t('userSettings.passwordSetSuccess')
    setTimeout(() => {
      closeSetPasswordModal()
    }, 2000)
  } else {
    setPasswordError.value = result.error
  }

  isSettingPassword.value = false
}

// 刪除帳號相關狀態
const showDeleteAccountModal = ref(false)
const isDeletingAccount = ref(false)
const deleteAccountError = ref('')
const deleteAccountForm = ref({
  confirmation: '',
  password: ''
})

function closeDeleteAccountModal() {
  showDeleteAccountModal.value = false
  deleteAccountForm.value = { confirmation: '', password: '' }
  deleteAccountError.value = ''
}

async function confirmDeleteAccount() {
  deleteAccountError.value = ''

  // 驗證 email 確認
  if (deleteAccountForm.value.confirmation !== authStore.user?.email) {
    deleteAccountError.value = $t('userSettings.errorEmailConfirmMismatch')
    return
  }

  // 密碼用戶需輸入密碼
  if (authStore.hasPassword && !deleteAccountForm.value.password) {
    deleteAccountError.value = $t('userSettings.errorDeletePasswordRequired')
    return
  }

  isDeletingAccount.value = true

  const result = await authStore.deleteAccount(
    deleteAccountForm.value.password || null,
    deleteAccountForm.value.confirmation
  )

  if (result.success) {
    closeDeleteAccountModal()
    router.push('/login')
  } else {
    deleteAccountError.value = result.error || $t('userSettings.errorDeleteFailed')
  }

  isDeletingAccount.value = false
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

.settings-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

/* 使用者資訊顯示面板 - 像素風格 */
.user-display-wrapper {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  gap: 12px;
  margin: 90px 0 32px 0;
}

/* 面板內標籤 */
.panel-label {
  font-family: 'VT323', monospace;
  font-size: 11px;
  color: #888888;
  letter-spacing: 1px;
  margin-top: 4px;
  line-height: 1;
}

/* 顯示面板 */
.user-display-panel {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: 'VT323', monospace;
  font-size: 18px;
  color: #ffffff;
  background: #1a1a1a;
  padding: 10px 18px;
  border-radius: 10px;
  width: 280px;
  border: 14px solid #000000;
  letter-spacing: 2.5px;
}

.display-row-inline {
  display: flex;
  gap: 16px;
}

.display-row-inline .display-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.display-row-inline .display-row {
  border-bottom: none;
  padding: 0;
}

.user-display-panel .display-row {
  display: flex;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.user-display-panel .display-row:last-child {
  border-bottom: none;
}

.user-display-panel .display-value {
  color: #e4e4e4;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 分隔線 */
.user-display-panel .display-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, #ff8c00, transparent);
  margin: 8px 0;
  opacity: 0.5;
}

/* 使用量行 */
.user-display-panel .usage-row {
  border-bottom: none;
  padding-bottom: 2px;
}

.user-display-panel .usage-value {
  font-size: 14px;
  color: #ff8c00;
}

/* 進度條 */
.user-display-panel .display-bar {
  position: relative;
  height: 10px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 2px;
  margin-bottom: 0px;
  overflow: hidden;
}

.user-display-panel .display-bar:last-child {
  margin-bottom: 0;
}

.user-display-panel .bar-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background:
    repeating-linear-gradient(
      90deg,
      #ff8c00 0px,
      #ff8c00 4px,
      #1a1a1a 4px,
      #1a1a1a 6px
    );
  transition: width 0.3s ease;
  box-shadow: 0 0 6px rgba(255, 140, 0, 0.4);
}

.user-display-panel .bar-text {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  color: #ff8c00;
  text-shadow: 0 0 4px rgba(0, 0, 0, 0.9);
  z-index: 1;
}

.usage-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.usage-label-row .panel-label {
  margin-top: 0;
}

/* 主題色 icons */
.user-display-panel .display-row:has(.theme-icons) {
  padding: 0;
}

.user-display-panel .theme-icons {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-display-panel .theme-icons svg {
  color: #1a1a1a;
  background: #333;
  padding: 6px;
  border-radius: 6px;
  width: 32px;
  height: 28px;
  transition: all 0.2s ease;
}

.user-display-panel .theme-icons svg.active {
  color: #000;
  background: #fff;
}

/* 方案層級 */
.user-display-panel .plan-tiers {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
}

.user-display-panel .plan-tiers span {
  color: #444;
  transition: color 0.2s ease;
}

.user-display-panel .plan-tiers span.active {
  color: #fff;
}


/* 方案指標 */
.plan-indicator-wrapper {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  align-self: center;
  border: 0.5px solid var(--main-text-light);
  border-radius: 10px;
  padding: 29px;
  width: 280px;
  box-sizing: border-box;
  position: relative;
}

.corner-screw {
  position: absolute;
  width: 14px;
  height: 14px;
  color: var(--main-text);
}

.corner-tl { top: 6px; left: 6px; transform: rotate(-45deg); }
.corner-tr { top: 6px; right: 6px; transform: rotate(45deg); }
.corner-bl { bottom: 6px; left: 6px; transform: rotate(45deg); }
.corner-br { bottom: 6px; right: 6px; transform: rotate(-45deg); }

.plan-indicator-title {
  font-family: 'VT323', monospace;
  font-size: 23px;
  margin-left: 15px;
  margin-bottom: 5px;
  color: var(--main-text);
  letter-spacing: 1px;
  opacity: 1;
}

.plan-indicator {
  display: flex;
  align-items: flex-start;
  gap: 15px;
  padding: 16px 30px;
  align-self: center;
}

.plan-indicator-pointer-track {
  position: relative;
  width: 60px;
  flex-shrink: 0;
  align-self: stretch;
}

.plan-pointer {
  position: absolute;
  width: 16px;
  height: 56px;
  color: var(--main-text);
  opacity: 0.75;
  /* 固定在 lines 容器垂直中心 */
  top: 35%;
  left: 50%;
  margin-top: -28px;
  margin-left: -8px;
  /* 旋轉中心：水平置中，牆壁下方 1/3（牆壁 y:20~60，高 40，1/3 from bottom ≈ y:47 → 78%） */
  transform-origin: 50% 78%;
  transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 旋轉角度：基準 90° 朝右，依各方案偏移 */
.plan-pointer.point-to-free       { transform: rotate(50deg); }
.plan-pointer.point-to-basic      { transform: rotate(79deg); }
.plan-pointer.point-to-pro        { transform: rotate(102deg); }
.plan-pointer.point-to-enterprise { transform: rotate(133deg); }

.plan-indicator-lines {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.plan-indicator-item {
  display: flex;
  align-items: center;
  gap: 0;
  cursor: pointer; /* 測試用 */
}

.plan-arc-wrapper {
  width: 56px;
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
}

.plan-arc {
  height: 16px;
  color: var(--main-text-light);
  opacity: 0.8;
}

.plan-arc.plan-arc-short {
  width: 40px;
}

.plan-arc.plan-arc-long {
  width: 56px;
}

.plan-indicator-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #aaa;
  flex-shrink: 0;
  margin-left: 12px;
  margin-right: 0px;
}

.plan-indicator-label {
  font-family: 'VT323', monospace;
  font-size: 14px;
  color: var(--main-text-light);
  letter-spacing: 1px;
  padding-left: 4px;
  opacity: 1;
  white-space: nowrap;
}

.plan-indicator-item.active .plan-arc {
  color: var(--main-text);
  opacity: 0.5;
}

.plan-indicator-item.active .plan-indicator-dot {
  background: var(--nav-active-bg);
}

.plan-indicator-item.active .plan-indicator-label {
  color: var(--main-text);
  opacity: 1;
  font-weight: 700;
}

.plan-indicator-actions {
  display: flex;
  gap: 14px;
  margin-top: 12px;
  margin-bottom: 5px;
  align-self: center;
}

.plan-btn {
  font-family: 'VT323', monospace;
  font-size: 15px;
  letter-spacing: 1px;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.plan-btn-outline {
  background: transparent;
  border: 1px solid var(--main-text-light);
  color: var(--main-text-light);
  opacity: 1;
}

.plan-btn-outline:hover {
  opacity: 0.8;
}

.plan-btn-primary {
  display: flex;
  align-items: center;
  gap: 5px;
  background: var(--nav-active-bg);
  border: 1px solid var(--main-text-light);
  color: #fff;
}

.plan-btn-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  animation: spin-icon 3s linear infinite;
}

@keyframes spin-icon {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.plan-btn-primary:hover {
  opacity: 0.85;
}

.settings-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  max-width: 800px;
  margin: 0 auto;
  justify-content: center;
  align-items: flex-start;
}

.settings-grid .card {
  width: 250px;
  min-width: 250px;
  max-width: 250px;
  box-sizing: border-box;
  border: 0.5px solid var(--main-text-light);
  border-radius: 10px;
  background: transparent;
  transition: all 0.3s ease;
  overflow: hidden;
  cursor: pointer;
}

.settings-grid .card.expanded {
  cursor: default;
}

.settings-grid .security-card,
.settings-grid .interface-card,
.settings-grid .security-card.expanded,
.settings-grid .interface-card.expanded {
  width: calc(50% - 12px);
  min-width: calc(50% - 12px);
  max-width: calc(50% - 12px);
}

.quota-card {
  width: 100% !important;
}

.user-info-card h2,
.interface-card h2,
.security-card h2,
.support-card h2,
.documents-card h2,
.team-card h2 {
  font-size: 1.25rem;
  color: var(--main-text);
  margin: 0;
  font-weight: 600;
}


.card-title-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon {
  flex-shrink: 0;
  color: var(--nav-active-bg);
  transition: color 0.3s ease;
}

.card-icon.active {
  color: var(--main-text-light);
}

.card-icon-person {
  flex-shrink: 0;
  margin-left: -6px;
  margin-top: 12px;
  position: relative;
  z-index: 1;
}

.card-icon-person-left {
  margin-left: 0;
  margin-right: -6px;
  margin-top: 16px;
}

.card-icon-person-left-second {
  margin-left: -3px;
  margin-right: -32px;
  margin-top: 16px;
}

.card-icon-hands {
  flex-shrink: 0;
  margin-top: 18px;
  margin-left: -5px;
  margin-right: -8px;
}

.interface-card .card-icon-person {

  margin: 17px 10px -4px -22px;
}

.card-icon-person-second {
  margin-left: -10px;
}

.team-card .card-icon {
  margin-top: -4px;
}

.team-card .card-icon-person-left,
.team-card .card-icon-person-left-second {
  margin-top: 12px;
}

.team-card .card-icon-hands {
  margin-top: 14px;
}

.card-subtitle {
  font-size: 0.75rem;
  color: var(--main-text-light);
  margin: 6px 0 0 0;
  font-weight: 400;
  line-height: 1.4;
  opacity: 1;
  max-height: 40px;
  overflow: hidden;
  transition: opacity 0.3s ease 0.2s, max-height 0.2s ease 0.2s, margin 0.2s ease 0.2s;
}

.card-subtitle.hidden {
  opacity: 0;
  max-height: 0;
  margin: 0;
  overflow: hidden;
  transition: opacity 0s ease, max-height 0s ease, margin 0s ease;
}

/* 卡片 toggle */
.card-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
  transition: margin 0.3s ease;
}

.toggle-arrow {
  transition: transform 0.3s ease, opacity 0.3s ease;
  color: var(--main-text-light);
  opacity: 0;
}

.toggle-arrow.expanded {
  transform: rotate(180deg);
  opacity: 1;
}

.card-body {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s ease;
}

.card-body.expanded {
  max-height: 600px;
}

.link-item {
  text-decoration: none;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.link-item:hover {
  opacity: 0.7;
}

.link-item svg {
  color: var(--main-text-light);
  flex-shrink: 0;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.info-item:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 0.95rem;
  color: var(--main-text-light);
  font-weight: 500;
}

.info-value {
  font-size: 0.95rem;
  color: var(--main-text);
  font-weight: 600;
}

/* 介面設定樣式 */
.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.setting-item:last-child {
  border-bottom: none;
}

.setting-label {
  font-size: 0.95rem;
  color: var(--main-text-light);
  font-weight: 500;
}

/* 自訂下拉選單 */
.custom-select {
  position: relative;
  min-width: 140px;
}

.select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: var(--main-bg);
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--main-text);
  transition: all 0.2s ease;
}

.select-trigger:hover {
  background: rgba(163, 177, 198, 0.15);
}

.select-arrow {
  color: var(--main-text-light);
  transition: transform 0.2s ease;
}

.custom-select.open .select-arrow {
  transform: rotate(180deg);
}

.select-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 100%;
  background: var(--color-bg-light, #fff);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-8px);
  transition: all 0.2s ease;
  z-index: 100;
  overflow: hidden;
}

.custom-select.open .select-dropdown {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.select-option {
  padding: 10px 14px;
  font-size: 14px;
  color: var(--main-text);
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.select-option:hover {
  background: rgba(163, 177, 198, 0.15);
}

.select-option.active {
  background: var(--nav-active-bg);
  color: white;
}

/* 色調開關 */
.theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.theme-icon {
  color: var(--main-text-light);
  opacity: 0.6;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  cursor: pointer;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--color-divider);
  border-radius: 22px;
  transition: all 0.3s ease;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: all 0.3s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.toggle-switch.active .toggle-slider {
  background: var(--nav-active-bg);
}

.toggle-switch.active .toggle-slider::before {
  transform: translateX(18px);
}

/* 更改密碼按鈕 */
.change-password-btn {
  padding: 8px 16px;
  background: var(--main-primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.change-password-btn:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Modal 樣式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--color-overlay, rgba(0, 0, 0, 0.5));
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--upload-bg);
  border-radius: 16px;
  padding: 24px;
  min-width: 360px;
  max-width: 90%;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
}

.modal h3 {
  color: var(--main-primary);
  margin: 0 0 20px 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.modal-body {
  margin-bottom: 20px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: var(--main-text);
  font-size: 14px;
}

.form-input {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 8px;
  background: var(--color-bg);
  font-size: 14px;
  color: var(--main-text);
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: var(--main-primary);
  box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb), 0.15);
}

.form-input::placeholder {
  color: var(--main-text-light);
  opacity: 0.7;
}

.password-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.password-input-wrapper .form-input {
  padding-right: 40px;
}

.password-toggle {
  position: absolute;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--main-text-light);
  cursor: pointer;
  transition: all 0.2s ease;
}

.password-toggle:hover {
  color: var(--main-primary);
  background: rgba(var(--color-primary-rgb), 0.1);
}

.password-requirements {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-bg);
  border-radius: 8px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
}

.requirement {
  font-size: 0.8rem;
  color: var(--main-text-light);
  transition: color 0.2s ease;
}

.requirement.met {
  color: var(--color-success, #28a745);
  font-weight: 600;
}

.error-text {
  color: var(--color-danger, #dc3545);
  font-size: 14px;
  margin: 0;
}

.success-text {
  color: var(--color-success, #28a745);
  font-size: 14px;
  margin: 0;
}

.modal-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn-cancel,
.btn-confirm {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-cancel {
  background: var(--color-bg);
  color: var(--main-text);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
}

.btn-cancel:hover {
  background: var(--color-bg-light, rgba(163, 177, 198, 0.15));
}

.btn-confirm {
  background: var(--color-primary, var(--main-primary));
  color: white;
}

.btn-confirm:hover {
  opacity: 0.9;
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Google 綁定樣式 */
.google-setting {
  flex-wrap: wrap;
  gap: 12px;
}

.setting-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.setting-right {
  display: flex;
  align-items: center;
}

.connected-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.8rem;
  color: var(--color-success, #28a745);
  font-weight: 500;
}

.connected-status svg {
  flex-shrink: 0;
}

.google-bind-wrapper {
  min-height: 40px;
  display: flex;
  align-items: center;
}

.unbind-btn {
  padding: 8px 16px;
  background: transparent;
  color: var(--color-danger, #dc3545);
  border: 1px solid var(--color-danger, #dc3545);
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.unbind-btn:hover:not(:disabled) {
  background: var(--color-danger, #dc3545);
  color: white;
}

.unbind-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.google-message {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 0.85rem;
  margin-top: 12px;
}

.google-message.error {
  background: rgba(220, 53, 69, 0.1);
  color: var(--color-danger, #dc3545);
  border: 1px solid rgba(220, 53, 69, 0.2);
}

.google-message.success {
  background: rgba(40, 167, 69, 0.1);
  color: var(--color-success, #28a745);
  border: 1px solid rgba(40, 167, 69, 0.2);
}

.modal-description {
  color: var(--main-text-light);
  font-size: 0.9rem;
  margin: -10px 0 20px 0;
}

/* 刪除帳號 */
.delete-account-item {
  padding-top: 16px;
}

.delete-label {
  color: var(--main-text-light) !important;
}

.delete-account-btn {
  padding: 8px 16px;
  background: transparent;
  color: var(--color-danger, #dc3545);
  border: 1px solid var(--color-danger, #dc3545);
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.delete-account-btn:hover {
  background: var(--color-danger, #dc3545);
  color: white;
}

.delete-modal-title {
  color: var(--color-danger, #dc3545) !important;
}

.delete-description {
  color: var(--main-text);
  font-size: 0.9rem;
  margin: 0 0 8px 0;
}

.delete-items {
  margin: 0 0 12px 0;
  padding-left: 20px;
  color: var(--main-text-light);
  font-size: 0.85rem;
  line-height: 1.8;
}

.delete-warning {
  color: var(--color-danger, #dc3545);
  font-weight: 600;
  font-size: 0.9rem;
  margin: 0 0 16px 0;
}

.btn-delete {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--color-danger, #dc3545);
  color: white;
}

.btn-delete:hover {
  opacity: 0.9;
}

.btn-delete:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 配額卡片樣式 */

.quota-content {
  padding: 24px;
  background: var(--main-bg);
}

.quota-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid rgba(163, 177, 198, 0.2);
}

.quota-header h3 {
  margin: 0;
  font-size: 1.25rem;
  color: var(--main-primary);
  font-weight: 600;
}

.quota-tier {
  padding: 6px 16px;
  background: var(--main-bg);
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--main-primary);
}

.quota-items {
  display: grid;
  gap: 24px;
}

.quota-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.quota-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.95rem;
  color: var(--main-text);
  font-weight: 500;
}

.quota-value {
  font-weight: 600;
  color: var(--main-primary);
}

.quota-bar {
  height: 10px;
  background: var(--main-bg);
  border-radius: 8px;
  overflow: hidden;
}

.quota-progress {
  height: 100%;
  background: linear-gradient(90deg, var(--main-primary), var(--main-primary-light));
  border-radius: 8px;
  transition: width 0.3s ease, background 0.3s ease;
  box-shadow: 0 0 8px rgba(108, 139, 163, 0.3);
}

.quota-progress.quota-warning {
  background: linear-gradient(90deg, #ff6b35, #ff8c42);
  box-shadow: 0 0 8px rgba(255, 107, 53, 0.4);
}

.quota-remaining {
  font-size: 0.85rem;
  color: var(--main-text-light);
  text-align: right;
}

@media (max-width: 768px) {
  .settings-container {
    padding: 0 16px;
  }

  .user-display-wrapper {
    max-width: 100%;
    margin-top: 24px;
    margin-bottom: 24px;
    flex-wrap: wrap;
    justify-content: center;
  }

  .user-display-panel {
    min-width: auto;
    flex: 1;
  }

  .plan-indicator-wrapper {
    width: 100%;
    align-items: center;
    margin-top: 8px;
  }

  .plan-indicator {
    padding: 8px 16px;
  }

  .plan-indicator-title {
    margin-left: 15px;
    text-align: left;
    align-self: flex-start;
  }

  .settings-grid .card,
  .settings-grid .security-card,
  .settings-grid .interface-card,
  .settings-grid .security-card.expanded,
  .settings-grid .interface-card.expanded,
  .settings-grid .card.expanded {
    width: 100%;
    min-width: 100%;
    max-width: 100%;
  }

  .quota-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .quota-tier {
    align-self: flex-end;
  }
}

/* 小手機 */
@media (max-width: 480px) {
  .settings-container {
    padding: 0 12px;
  }

  .user-display-wrapper {
    gap: 8px;
    margin-bottom: 20px;
  }

  .display-labels .label-item {
    font-size: 10px;
  }

  .user-display-panel {
    font-size: 16px;
    padding: 12px 14px;
  }

  .user-display-panel .display-value {
    max-width: 160px;
    font-size: 15px;
  }

  .settings-grid {
    gap: 16px;
  }

  /* 卡片內間距調整 */
  .user-info-card,
  .interface-card {
    padding: 16px;
  }

  .user-info-card h2,
  .interface-card h2 {
    font-size: 1.1rem;
    margin-bottom: 16px;
  }

  .info-item,
  .setting-item {
    padding: 10px 0;
    flex-wrap: wrap;
    gap: 8px;
  }

  .info-label,
  .setting-label,
  .info-value {
    font-size: 0.9rem;
  }

  /* 下拉選單在小屏優化 */
  .custom-select {
    min-width: 120px;
  }

  .select-trigger {
    padding: 10px 12px;
    font-size: 14px;
    min-height: 44px;
  }

  .select-dropdown {
    max-height: 200px;
    overflow-y: auto;
  }

  .select-option {
    padding: 12px 14px;
    min-height: 44px;
  }

  /* 配額卡片調整 */
  .quota-content {
    padding: 16px;
  }

  .quota-header h3 {
    font-size: 1.1rem;
  }

  .quota-tier {
    padding: 4px 12px;
    font-size: 0.8rem;
  }

  .quota-items {
    gap: 16px;
  }

  .quota-label {
    font-size: 0.85rem;
    flex-wrap: wrap;
  }

  .quota-value {
    font-size: 0.85rem;
  }

  .quota-remaining {
    font-size: 0.8rem;
  }

  /* toggle 開關觸控優化 */
  .toggle-switch {
    width: 44px;
    height: 24px;
  }
}
</style>
