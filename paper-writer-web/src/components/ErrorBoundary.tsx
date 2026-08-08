import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** 页面运行出错时显示错误信息，而不是空白页。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
          <div className="w-full max-w-md rounded-2xl border border-red-200 bg-white p-6 shadow-lg">
            <h1 className="mb-2 text-lg font-semibold text-red-600">
              页面出错了
            </h1>
            <p className="mb-3 break-words text-sm text-slate-600">
              {this.state.error.message || String(this.state.error)}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              刷新重试
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
