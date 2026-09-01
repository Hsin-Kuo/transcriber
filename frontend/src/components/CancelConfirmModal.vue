<template>
  <Teleport to="body">
    <div v-if="modelValue" class="cc-overlay" @click.self="close">
      <div class="cc-box" role="dialog" aria-modal="true">
        <h3 class="cc-title">{{ $t('userSettings.subscription.cancelConfirmTitle') }}</h3>
        <p class="cc-lead">{{ periodEndText }}</p>
        <ul class="cc-rights">
          <li>{{ $t('userSettings.subscription.cancelConfirmRevert') }}</li>
          <li>{{ $t('userSettings.subscription.cancelConfirmNote') }}</li>
        </ul>
        <div class="cc-actions">
          <button class="cc-btn cc-keep" @click="close">
            {{ $t('userSettings.subscription.keepPlanBtn') }}
          </button>
          <button class="cc-btn cc-confirm" :disabled="canceling" @click="$emit('confirm')">
            {{ canceling ? $t('userSettings.processing') : $t('userSettings.subscription.cancelConfirmBtn') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  canceling: { type: Boolean, default: false },
  // 已格式化的期末日期字串（父層負責格式化）；沒有就用無日期版文案
  periodEndLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'confirm'])

const periodEndText = computed(() =>
  props.periodEndLabel
    ? $t('userSettings.subscription.cancelConfirmPeriodEnd', { date: props.periodEndLabel })
    : $t('userSettings.subscription.cancelConfirmPeriodEndNoDate')
)

function close() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
.cc-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 20px;
}
.cc-box {
  background: var(--upload-bg, #fff);
  border-radius: 12px;
  padding: 24px;
  max-width: 440px;
  width: 100%;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}
.cc-title {
  margin: 0 0 12px;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--main-text);
}
.cc-lead {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--main-text);
  line-height: 1.6;
}
.cc-rights {
  margin: 0 0 20px;
  padding-left: 18px;
  color: var(--main-text-light);
  font-size: 13px;
  line-height: 1.7;
}
.cc-rights li { margin-bottom: 6px; }
.cc-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.cc-btn {
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  transition: opacity 0.2s ease;
}
.cc-keep {
  background: transparent;
  border-color: var(--color-divider, rgba(163, 177, 198, 0.4));
  color: var(--main-text);
}
.cc-confirm {
  background: var(--color-danger, #dc3545);
  color: #fff;
}
.cc-confirm:disabled { opacity: 0.6; cursor: not-allowed; }
.cc-btn:hover:not(:disabled) { opacity: 0.9; }
</style>
