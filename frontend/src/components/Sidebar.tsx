import React from 'react';

export const Sidebar: React.FC<{
  children: React.ReactNode;
}> = ({ children }) => {
  return (
    <aside className="w-full md:w-80 h-full app-card-soft p-4 flex flex-col gap-4 overflow-hidden rounded-3xl glass-card">
      {children}
    </aside>
  );
};
