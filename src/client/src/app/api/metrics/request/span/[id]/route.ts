import { getRequestViaSpanId } from "@/lib/platform/request";

export async function GET(_: Request, context: any) {
	const { id } = context.params || {};

	if (!id)
		return Response.json("No span id provided", {
			status: 400,
		});

	const res: any = await getRequestViaSpanId(id);
	return Response.json(res);
}