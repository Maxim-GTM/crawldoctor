import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { hubSignIn } from '../utils/api';

interface User {
  id: number;
  username: string;
  email: string;
  full_name?: string;
  is_superuser: boolean;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  signOutUrl: string | null;
  signOut: () => void;
  retry: () => void;
  error: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [signOutUrl, setSignOutUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Check if user is authenticated
  const isAuthenticated = Boolean(user && token);

  // Sign in through the GTM Hub on every page load, so a hub sign-out or a
  // revoked dashboard applies as soon as the page is opened again. People who
  // aren't signed in (or have no access) are sent to the hub instead.
  const signIn = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const session = await hubSignIn();
      setToken(session.access_token);
      setUser(session.user);
      setSignOutUrl(session.signout_url);
    } catch (err: any) {
      console.error('Hub sign-in failed:', err);
      setError(
        err.response?.status === 503
          ? 'Sign-in service unavailable, try again shortly.'
          : 'Could not sign you in.'
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    signIn();
  }, [signIn]);

  // Used by the "Sign out" link, which then takes the browser to the hub's sign-out page
  const signOut = () => {
    localStorage.removeItem('auth_token');
  };

  const value: AuthContextType = {
    user,
    token,
    signOutUrl,
    signOut,
    retry: signIn,
    error,
    isLoading,
    isAuthenticated,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};
