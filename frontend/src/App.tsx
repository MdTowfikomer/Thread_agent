import React, { useState, useEffect } from 'react';
import { LandingPage } from './pages/LandingPage';
import { AuthPage } from './pages/AuthPage';
import { WorkspacePage } from './pages/WorkspacePage';

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
    setCurrentRoute(route);
    window.scrollTo(0, 0);
  };

  if (currentRoute === '/') {
    return <LandingPage onOpenWorkspace={() => navigate('/auth')} />;
  }

  if (currentRoute === '/auth') {
    return <AuthPage onBack={() => navigate('/')} onAuthenticated={() => navigate('/app')} />;
  }

  return <WorkspacePage onNavigate={navigate} currentRoute={currentRoute} />;
}

export default App;
