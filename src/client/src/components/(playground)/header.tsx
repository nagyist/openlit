"use client";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import DatabaseConfigSwitch from "./database-config-switch";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Moon, Sun, User } from "lucide-react";
import { useRootStore } from "@/store";
import { getUserDetails, resetUser } from "@/selectors/user";
import useTheme from "@/utils/hooks/useTheme";
import Link from "next/link";
import RefreshRate from "./filter/refresh-rate";
import { usePostHog } from "posthog-js/react";
import { useEffect } from "react";
import { usePageHeader } from "@/selectors/page";
import DescriptionTooltip from "../common/description-tooltip";

const ThemeToggleSwitch = () => {
	const { toggleTheme } = useTheme();
	return (
		<Button
			variant="ghost"
			size={"icon"}
			className="rounded-full dark:text-white"
			onClick={toggleTheme}
		>
			<Moon className="dark:hidden block size-5" />
			<Sun className="dark:block hidden size-5" />
		</Button>
	);
};

const DashboardTitleMap = {
	"d": "Dashboard",
};

export default function Header() {
	const posthog = usePostHog();
	const pathname = usePathname();
	const user = useRootStore(getUserDetails);
	const resetUserFn = useRootStore(resetUser);
	const onClickSignout = () => {
		posthog?.reset();
		signOut();
		resetUserFn();
	};

	useEffect(() => {
		if (user?.id) {
			posthog?.identify(user.id);
		}
	}, [user]);

	const { header, setHeader } = usePageHeader();

	
	useEffect(() => {
		const titleKey = pathname.substring(1).replaceAll("-", " ").split("/")[0];
		setHeader({
			title: DashboardTitleMap[titleKey as keyof typeof DashboardTitleMap] || titleKey,
			breadcrumbs: [],
		});
	}, [pathname, setHeader]);

	return (
		<header className="flex h-[57px] items-center gap-1 border-b dark:border-stone-800 px-4 sm:px-6">
			<div className="flex items-center gap-2 grow">
				<h1 className="text-xl font-semibold capitalize dark:text-white">{header.title}</h1>
				{header.description && (
					<DescriptionTooltip description={header.description} className="ml-2 h-4 w-4 text-stone-900 dark:text-stone-300" />
				)}
			</div>
			<DatabaseConfigSwitch />
			<RefreshRate />
			<DropdownMenu>
				<DropdownMenuTrigger asChild>
					<Button
						variant="ghost"
						size="icon"
						className="p-0.5 size-8 overflow-hidden rounded-full"
					>
						<User className="overflow-hidden rounded-full dark:text-white" />
					</Button>
				</DropdownMenuTrigger>
				<DropdownMenuContent align="end">
					<DropdownMenuItem disabled>{user?.email}</DropdownMenuItem>
					<DropdownMenuSeparator />
					<DropdownMenuItem asChild>
						<Link href="/settings/profile">Edit details</Link>
					</DropdownMenuItem>
					<DropdownMenuItem onClick={onClickSignout}>Logout</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>
			<ThemeToggleSwitch />
		</header>
	);
}
