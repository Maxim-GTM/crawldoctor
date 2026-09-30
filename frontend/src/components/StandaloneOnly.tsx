import React, { useSyncExternalStore } from 'react';

const subscribe = () => () => {};

/**
 * Shows its children only when CrawlDoctor is opened on its own. Inside the GTM Hub's frame they'd
 * repeat what the hub's own sidebar already has (the account and Sign out), so they're left out.
 */
const StandaloneOnly: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const standalone = useSyncExternalStore(subscribe, () => window.self === window.top);
  return standalone ? <>{children}</> : null;
};

export default StandaloneOnly;
