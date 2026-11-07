import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/syne'
import '@fontsource-variable/dm-sans'
import '@fontsource-variable/jetbrains-mono'
import './styleguide.css'
import { ThemeProvider } from '../contexts/ThemeContext'
import { Styleguide } from './Styleguide'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <Styleguide />
    </ThemeProvider>
  </React.StrictMode>,
)
