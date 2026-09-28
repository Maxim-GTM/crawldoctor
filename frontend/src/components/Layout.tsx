import React, { useState } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import {
  ChartBarIcon,
  ClockIcon,
  CogIcon,
  DocumentTextIcon,
  HomeIcon,
  UserIcon,
  UserGroupIcon,
  Bars3Icon,
  XMarkIcon,
  ArrowPathIcon,
  BoltIcon,
} from '@heroicons/react/24/outline';
import { useAuth } from '../contexts/AuthContext';
import { adminAPI } from '../utils/api';

const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: HomeIcon },
  { name: 'Live Data', href: '/live-data', icon: BoltIcon },
  { name: 'Sessions', href: '/sessions', icon: ClockIcon },
  { name: 'Journeys', href: '/journeys', icon: ChartBarIcon },
  { name: 'Funnels', href: '/funnels', icon: CogIcon },
  { name: 'Leads', href: '/leads', icon: UserIcon },
  { name: 'Users', href: '/users', icon: UserGroupIcon },
  { name: 'Embed Guide', href: '/embed', icon: DocumentTextIcon },
];

const Layout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [processing, setProcessing] = useState(false);
  const { user, signOutUrl, signOut } = useAuth();
  const location = useLocation();
  const displayName = user?.full_name || user?.username;

  const isActivePath = (path: string) => {
    return location.pathname === path;
  };

  const handleProcessData = async () => {
    if (processing) return;
    setProcessing(true);
    try {
      await adminAPI.rebuildSummaries(30);
      alert('Data processing started. It will run in the background.');
    } catch (error) {
      console.error(error);
      alert('Failed to start processing.');
    } finally {
      setProcessing(false);
    }
  };

  const allNavigation = navigation;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Mobile sidebar */}
      <div className={`relative z-50 lg:hidden ${sidebarOpen ? '' : 'hidden'}`}>
        <div className="fixed inset-0 bg-gray-900/80" onClick={() => setSidebarOpen(false)} />

        <div className="fixed inset-0 flex">
          <div className="relative mr-16 flex w-full max-w-xs flex-1">
            <div className="absolute left-full top-0 flex w-16 justify-center pt-5">
              <button
                type="button"
                className="-m-2.5 p-2.5"
                onClick={() => setSidebarOpen(false)}
              >
                <XMarkIcon className="h-6 w-6 text-white" />
              </button>
            </div>

            <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white px-6 pb-2">
              <div className="flex h-16 shrink-0 items-center gap-x-2">
                <h1 className="text-xl font-bold text-gradient">🕷️ CrawlDoctor</h1>
                <span className="text-xs text-gray-400">v1.1.0</span>
              </div>
              <nav className="flex flex-1 flex-col">
                <ul className="flex flex-1 flex-col gap-y-7">
                  <li>
                    <ul className="-mx-2 space-y-1">
                      {allNavigation.map((item) => (
                        <li key={item.name}>
                          <Link
                            to={item.href}
                            className={`group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold ${isActivePath(item.href)
                              ? 'bg-primary-50 text-primary-700'
                              : 'text-gray-700 hover:text-primary-700 hover:bg-gray-50'
                              }`}
                            onClick={() => setSidebarOpen(false)}
                          >
                            <item.icon className="h-6 w-6 shrink-0" />
                            {item.name}
                          </Link>
                        </li>
                      ))}
                      <li>
                        <button
                          onClick={handleProcessData}
                          disabled={processing}
                          className={`group flex w-full gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold text-gray-700 hover:text-primary-700 hover:bg-gray-50 ${processing ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                          <ArrowPathIcon className={`h-6 w-6 shrink-0 ${processing ? 'animate-spin' : ''}`} />
                          {processing ? 'Processing...' : 'Process Data'}
                        </button>
                      </li>
                    </ul>
                  </li>
                </ul>
              </nav>
            </div>
          </div>
        </div>
      </div>

      {/* Static sidebar for desktop */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-72 lg:flex-col">
        <div className="flex grow flex-col gap-y-5 overflow-y-auto border-r border-gray-200 bg-white px-6">
          <div className="flex h-16 shrink-0 items-center gap-x-2">
            <h1 className="text-xl font-bold text-gradient">🕷️ CrawlDoctor</h1>
            <span className="text-xs text-gray-400">v1.1.0</span>
          </div>
          <nav className="flex flex-1 flex-col">
            <ul className="flex flex-1 flex-col gap-y-7">
              <li>
                <ul className="-mx-2 space-y-1">
                  {allNavigation.map((item) => (
                    <li key={item.name}>
                      <Link
                        to={item.href}
                        className={`group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold ${isActivePath(item.href)
                          ? 'bg-primary-50 text-primary-700'
                          : 'text-gray-700 hover:text-primary-700 hover:bg-gray-50'
                          }`}
                      >
                        <item.icon className="h-6 w-6 shrink-0" />
                        {item.name}
                      </Link>
                    </li>
                  ))}
                  <li>
                    <button
                      onClick={handleProcessData}
                      disabled={processing}
                      className={`group flex w-full gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold text-gray-700 hover:text-primary-700 hover:bg-gray-50 ${processing ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      <ArrowPathIcon className={`h-6 w-6 shrink-0 ${processing ? 'animate-spin' : ''}`} />
                      {processing ? 'Processing...' : 'Process Data'}
                    </button>
                  </li>
                </ul>
              </li>
              <li className="-mx-6 mt-auto">
                <div className="flex items-center gap-x-4 px-6 py-3 text-sm font-semibold leading-6 text-gray-900">
                  <div className="h-8 w-8 rounded-full bg-primary-100 flex items-center justify-center">
                    <UserIcon className="h-5 w-5 text-primary-600" />
                  </div>
                  <span className="sr-only">Your profile</span>
                  <div className="flex-1">
                    <div className="text-sm font-medium">{displayName}</div>
                    <div className="text-xs text-gray-500">{user?.email}</div>
                  </div>
                  {/* Signing out happens in the GTM Hub; _top leaves the hub's iframe */}
                  {signOutUrl && (
                    <a
                      href={signOutUrl}
                      target="_top"
                      onClick={signOut}
                      className="text-gray-400 hover:text-gray-600"
                      title="Sign out"
                    >
                      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                      </svg>
                    </a>
                  )}
                </div>
              </li>
            </ul>
          </nav>
        </div>
      </div>

      {/* Main content */}
      <div className="lg:pl-72">
        {/* Top bar */}
        <div className="sticky top-0 z-40 flex h-16 shrink-0 items-center gap-x-4 border-b border-gray-200 bg-white px-4 shadow-sm sm:gap-x-6 sm:px-6 lg:px-8">
          <button
            type="button"
            className="-m-2.5 p-2.5 text-gray-700 lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Bars3Icon className="h-6 w-6" />
          </button>

          <div className="flex flex-1 gap-x-4 self-stretch lg:gap-x-6">
            <div className="flex flex-1"></div>
            <div className="flex items-center gap-x-4 lg:gap-x-6">
              {/* User menu */}
              <div className="flex items-center gap-x-2">
                <span className="text-sm text-gray-700">
                  Welcome, {displayName}
                </span>
                {user?.is_superuser && (
                  <span className="badge badge-blue">Admin</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Main content area */}
        <main className="py-8">
          <div className="px-4 sm:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

export default Layout;
