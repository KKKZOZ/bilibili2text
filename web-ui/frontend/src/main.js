import { createApp } from 'vue'
import '@fontsource/manrope/500.css'
import '@fontsource/manrope/700.css'
import App from './App.vue'
import router from './router.js'
import './style.css'

createApp(App).use(router).mount('#app')
