<template>
  <div class="google-signin-wrapper">
    <div
      ref="googleButtonRef"
      class="google-button-container"
    ></div>
    <div v-if="!isLoaded" class="google-button-placeholder">
      <span class="loading-text">{{ t('auth.loadingGoogle') }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

// 將 vue-i18n 的 locale 轉換為 Google 的格式 (zh-TW -> zh_TW)
const googleLocale = computed(() => {
  return locale.value.replace('-', '_')
})

const props = defineProps({
  clientId: {
    type: String,
    required: true
  },
  buttonText: {
    type: String,
    default: 'signin_with' // 'signin_with', 'signup_with', 'continue_with'
  },
  theme: {
    type: String,
    default: 'outline' // 'outline', 'filled_blue', 'filled_black'
  },
  size: {
    type: String,
    default: 'large' // 'small', 'medium', 'large'
  },
  width: {
    type: Number,
    default: 300
  }
})

const emit = defineEmits(['success', 'error'])

const googleButtonRef = ref(null)
const isLoaded = ref(false)
const currentLoadedLocale = ref('')

function handleCredentialResponse(response) {
  if (response.credential) {
    emit('success', response.credential)
  } else {
    emit('error', 'No credential received')
  }
}

// 動態載入 Google SDK（帶語言參數）
function loadGoogleSDK(lang) {
  return new Promise((resolve) => {
    // 檢查是否已經載入相同語言的 SDK
    if (window.google?.accounts?.id && currentLoadedLocale.value === lang) {
      resolve()
      return
    }

    // 移除舊的 SDK script
    const oldScript = document.getElementById('google-gsi-script')
    if (oldScript) {
      oldScript.remove()
      // 清除 Google 全域變數以便重新初始化
      delete window.google
    }

    // 創建新的 script 標籤
    const script = document.createElement('script')
    script.id = 'google-gsi-script'
    script.src = `https://accounts.google.com/gsi/client?hl=${lang}`
    script.async = true
    script.defer = true
    script.onload = () => {
      currentLoadedLocale.value = lang
      resolve()
    }
    document.head.appendChild(script)
  })
}

async function initGoogleSignIn() {
  const lang = googleLocale.value

  // 載入 SDK（如果需要）
  await loadGoogleSDK(lang)

  if (!window.google?.accounts?.id) {
    // SDK 尚未準備好，等待後重試
    setTimeout(initGoogleSignIn, 100)
    return
  }

  try {
    window.google.accounts.id.initialize({
      client_id: props.clientId,
      callback: handleCredentialResponse,
      auto_select: false,
      cancel_on_tap_outside: true
    })

    if (googleButtonRef.value) {
      // 清空容器以便重新渲染
      googleButtonRef.value.innerHTML = ''

      window.google.accounts.id.renderButton(googleButtonRef.value, {
        type: 'standard',
        theme: props.theme,
        size: props.size,
        text: props.buttonText,
        width: props.width,
        locale: lang
      })
      isLoaded.value = true
    }
  } catch (err) {
    console.error('Google Sign-In init error:', err)
    emit('error', err.message)
  }
}

onMounted(() => {
  initGoogleSignIn()
})

// 如果 clientId 變更，重新初始化
watch(() => props.clientId, () => {
  if (props.clientId) {
    initGoogleSignIn()
  }
})

// 當語言變更時，重新載入 SDK 並渲染按鈕
watch(locale, async () => {
  isLoaded.value = false
  await initGoogleSignIn()
})
</script>

<style scoped>
.google-signin-wrapper {
  display: flex;
  justify-content: center;
  min-height: 44px;
}

.google-button-container {
  display: flex;
  justify-content: center;
}

.google-button-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 24px;
  border: 1px solid #dadce0;
  border-radius: 4px;
  background: #fff;
  color: #5f6368;
  font-size: 14px;
}

.loading-text {
  opacity: 0.7;
}
</style>
