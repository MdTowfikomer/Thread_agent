import React, { useState, useEffect } from 'react';
import { LandingPage } from './pages/LandingPage';
import { AuthPage } from './pages/AuthPage';
import { AccountWorkspacePage } from './pages/AccountWorkspacePage';
import { InvitationPage } from './pages/InvitationPage';

export function App() {
  const [currentRoute, setCurrentRoute] = useState<string>(() => {
    return window.location.pathname || '/';
  });

  useEffect(() => {
    const handlePopState = () => {
      setCurrentRoute(window.location.pathname || '/');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (route: string) => {
    window.history.pushState({}, '', route);
    setCurrentRoute(route.split('?')[0]);
    window.scrollTo(0, 0);
  };

  if (currentRoute === '/') {
    return <LandingPage onOpenWorkspace={() => navigate('/auth')} />;
  }

  if (currentRoute === '/auth') {
    return <AuthPage onBack={() => navigate('/')} onAuthenticated={() => {
      const returnTo = new URLSearchParams(window.location.search).get('returnTo') || '';
      navigate(/^\/invite\/[A-Za-z0-9_-]+$/.test(returnTo) ? returnTo : '/app');
    }} />;
  }

  if (currentRoute.startsWith('/invite/')) return <InvitationPage token={currentRoute.slice('/invite/'.length)} onNavigate={navigate} />;
  return <AccountWorkspacePage onNavigate={navigate} currentRoute={currentRoute} />;
}

export default App;
