import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { NotificationProvider } from './contexts/NotificationContext';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import EmbedGuide from './pages/EmbedGuide';
import NotFound from './pages/NotFound';
import Sessions from './pages/Sessions';
import Users from './pages/Users';
import Journeys from './pages/Journeys';
import Funnels from './pages/Funnels';
import Leads from './pages/Leads';
import LiveData from './pages/LiveData';

function App() {
  return (
    <AuthProvider>
      <NotificationProvider>
        <div className="App min-h-screen bg-gray-50">
          <Routes>
            {/* Sign-in happens in the GTM Hub; keep old /login links working */}
            <Route path="/login" element={<Navigate to="/dashboard" replace />} />
            
            {/* Protected routes */}
            <Route path="/" element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="sessions" element={<Sessions />} />
              <Route path="journeys" element={<Journeys />} />
              <Route path="funnels" element={<Funnels />} />
              <Route path="leads" element={<Leads />} />
              <Route path="users" element={<Users />} />
              <Route path="live-data" element={<LiveData />} />
              <Route path="embed" element={<EmbedGuide />} />
            </Route>
            
            {/* 404 route */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </NotificationProvider>
    </AuthProvider>
  );
}

export default App;
