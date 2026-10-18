import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from './queryClient'
import { App } from './App'
import { AuthProvider } from './auth/AuthContext'
import { TechnicalModeProvider } from './presentation/TechnicalModeContext'
import './design/fonts'
import './styles.css'
const queryClient=createQueryClient()
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={queryClient}><AuthProvider><TechnicalModeProvider><BrowserRouter><App/></BrowserRouter></TechnicalModeProvider></AuthProvider></QueryClientProvider></React.StrictMode>)
