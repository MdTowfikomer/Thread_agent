import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { OrganizationWorkspace, ChatMessage, UserRole } from './types';
import { getWorkspace, sendChatMessage } from './api';

export function App() {
  const [workspace, setWorkspace] = useState<OrganizationWorkspace | null>(null);
  const [userRole, setUserRole] = useState<UserRole>('organizer');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    getWorkspace('gdg_mcet')
      .then(data => {
        setWorkspace(data);
      })
      .catch(err => {
        console.error('Failed to load workspace from backend:', err);
      });
  }, []);

  const handleSendMessage = async (query: string) => {
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const response = await sendChatMessage(query, workspace?.id || 'gdg_mcet', userRole);

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        role_agent: response.role_agent,
        citations: response.citations,
        confidence_score: response.confidence_score,
        trace: response.trace
      };

      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: `Error retrieving institutional context: ${err.message || 'Unknown network error'}. Please ensure the FastAPI backend is running.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      <Navbar
        workspaceName={workspace?.name || 'GDG MCET'}
        userRole={userRole}
        onUserRoleChange={setUserRole}
      />

      <div className="flex-1 flex overflow-hidden">
        <Sidebar
          workspace={workspace}
          onSelectPrompt={handleSendMessage}
          userRole={userRole}
        />

        <ChatArea
          messages={messages}
          loading={loading}
          onSendMessage={handleSendMessage}
          workspaceName={workspace?.name || 'GDG MCET'}
          userRole={userRole}
        />
      </div>
    </div>
  );
}

export default App;
