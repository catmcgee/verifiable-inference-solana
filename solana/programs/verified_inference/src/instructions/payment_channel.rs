use anchor_lang::prelude::*;
use anchor_spl::token::{self, CloseAccount, Mint, Token, TokenAccount, TransferChecked};

use crate::constants::*;
use crate::ed25519::require_ed25519_verification;
use crate::error::VerifiedInferenceError;
use crate::state::{ChannelAccount, ChannelStatus};

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct OpenChannelArgs {
    pub channel_id: [u8; 32],
    pub authorized_signer: [u8; 32],
    pub deposit: u64,
    pub grace_seconds: u32,
}

#[derive(Accounts)]
#[instruction(args: OpenChannelArgs)]
pub struct OpenChannel<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,

    /// CHECK: The payee only contributes its public key to the channel PDA and
    /// receives tokens through an owner-checked token account at finalization.
    pub payee: UncheckedAccount<'info>,

    #[account(
        init,
        payer = payer,
        space = 8 + ChannelAccount::INIT_SPACE,
        seeds = [
            CHANNEL_SEED,
            payer.key().as_ref(),
            payee.key().as_ref(),
            args.channel_id.as_ref()
        ],
        bump
    )]
    pub channel: Account<'info, ChannelAccount>,

    pub mint: Account<'info, Mint>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = payer
    )]
    pub payer_token: Account<'info, TokenAccount>,

    #[account(
        init,
        payer = payer,
        token::mint = mint,
        token::authority = channel,
        seeds = [CHANNEL_VAULT_SEED, channel.key().as_ref()],
        bump
    )]
    pub vault: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

pub fn handle_open_channel(ctx: Context<OpenChannel>, args: OpenChannelArgs) -> Result<()> {
    require!(
        args.deposit > 0,
        VerifiedInferenceError::InvalidChannelAmount
    );
    require!(
        (MIN_CHANNEL_GRACE_SECONDS..=MAX_CHANNEL_GRACE_SECONDS).contains(&args.grace_seconds),
        VerifiedInferenceError::InvalidChannelGracePeriod
    );

    token::transfer_checked(
        CpiContext::new(
            ctx.accounts.token_program.key(),
            TransferChecked {
                from: ctx.accounts.payer_token.to_account_info(),
                mint: ctx.accounts.mint.to_account_info(),
                to: ctx.accounts.vault.to_account_info(),
                authority: ctx.accounts.payer.to_account_info(),
            },
        ),
        args.deposit,
        ctx.accounts.mint.decimals,
    )?;

    let channel = &mut ctx.accounts.channel;
    channel.payer = ctx.accounts.payer.key();
    channel.payee = ctx.accounts.payee.key();
    channel.mint = ctx.accounts.mint.key();
    channel.vault = ctx.accounts.vault.key();
    channel.authorized_signer = args.authorized_signer;
    channel.channel_id = args.channel_id;
    channel.opened_slot = Clock::get()?.slot;
    channel.deposit = args.deposit;
    channel.authorized_cumulative = 0;
    channel.settled = 0;
    channel.close_requested_at = 0;
    channel.grace_seconds = args.grace_seconds;
    channel.status = ChannelStatus::Open;
    channel.bump = ctx.bumps.channel;
    channel.vault_bump = ctx.bumps.vault;
    Ok(())
}

#[derive(Accounts)]
pub struct TopUpChannel<'info> {
    #[account(mut, address = channel.payer)]
    pub payer: Signer<'info>,

    #[account(mut, has_one = mint, has_one = vault)]
    pub channel: Account<'info, ChannelAccount>,

    pub mint: Account<'info, Mint>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = payer
    )]
    pub payer_token: Account<'info, TokenAccount>,

    #[account(mut, token::mint = mint, token::authority = channel)]
    pub vault: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

pub fn handle_top_up_channel(ctx: Context<TopUpChannel>, amount: u64) -> Result<()> {
    require!(amount > 0, VerifiedInferenceError::InvalidChannelAmount);
    require!(
        ctx.accounts.channel.status == ChannelStatus::Open,
        VerifiedInferenceError::ChannelNotOpen
    );

    token::transfer_checked(
        CpiContext::new(
            ctx.accounts.token_program.key(),
            TransferChecked {
                from: ctx.accounts.payer_token.to_account_info(),
                mint: ctx.accounts.mint.to_account_info(),
                to: ctx.accounts.vault.to_account_info(),
                authority: ctx.accounts.payer.to_account_info(),
            },
        ),
        amount,
        ctx.accounts.mint.decimals,
    )?;

    ctx.accounts.channel.deposit = ctx
        .accounts
        .channel
        .deposit
        .checked_add(amount)
        .ok_or(VerifiedInferenceError::ArithmeticOverflow)?;
    Ok(())
}

#[derive(Accounts)]
pub struct SettleChannel<'info> {
    #[account(mut)]
    pub channel: Account<'info, ChannelAccount>,

    /// CHECK: Address constrained to the instructions sysvar and introspected.
    #[account(address = solana_instructions_sysvar::ID)]
    pub instructions_sysvar: UncheckedAccount<'info>,
}

pub fn voucher_message(
    channel: &Pubkey,
    cumulative_authorized: u64,
    expires_at: i64,
) -> [u8; CHANNEL_VOUCHER_MSG_LEN] {
    let mut message = [0u8; CHANNEL_VOUCHER_MSG_LEN];
    message[0..32].copy_from_slice(channel.as_ref());
    message[32..40].copy_from_slice(&cumulative_authorized.to_le_bytes());
    message[40..48].copy_from_slice(&expires_at.to_le_bytes());
    message
}

pub fn handle_settle_channel(
    ctx: Context<SettleChannel>,
    cumulative_authorized: u64,
    cumulative_settlement: u64,
    expires_at: i64,
) -> Result<()> {
    let channel = &mut ctx.accounts.channel;
    require!(
        channel.status == ChannelStatus::Open || channel.status == ChannelStatus::Closing,
        VerifiedInferenceError::ChannelNotOpen
    );
    require!(
        expires_at == 0 || expires_at >= Clock::get()?.unix_timestamp,
        VerifiedInferenceError::VoucherExpired
    );
    require!(
        cumulative_authorized >= channel.authorized_cumulative,
        VerifiedInferenceError::VoucherWentBackwards
    );
    require!(
        cumulative_settlement >= channel.settled,
        VerifiedInferenceError::SettlementWentBackwards
    );
    require!(
        cumulative_settlement <= cumulative_authorized,
        VerifiedInferenceError::SettlementExceedsAuthorization
    );
    require!(
        cumulative_authorized <= channel.deposit,
        VerifiedInferenceError::AuthorizationExceedsDeposit
    );

    let message = voucher_message(&channel.key(), cumulative_authorized, expires_at);
    require_ed25519_verification(
        &ctx.accounts.instructions_sysvar,
        &channel.authorized_signer,
        &message,
    )?;

    channel.authorized_cumulative = cumulative_authorized;
    channel.settled = cumulative_settlement;
    Ok(())
}

#[derive(Accounts)]
pub struct RequestChannelClose<'info> {
    #[account(address = channel.payer)]
    pub payer: Signer<'info>,

    #[account(mut)]
    pub channel: Account<'info, ChannelAccount>,
}

pub fn handle_request_channel_close(ctx: Context<RequestChannelClose>) -> Result<()> {
    let channel = &mut ctx.accounts.channel;
    require!(
        channel.status == ChannelStatus::Open,
        VerifiedInferenceError::ChannelNotOpen
    );
    channel.status = ChannelStatus::Closing;
    channel.close_requested_at = Clock::get()?.unix_timestamp;
    Ok(())
}

#[derive(Accounts)]
pub struct FinalizeChannel<'info> {
    #[account(mut)]
    pub caller: Signer<'info>,

    #[account(
        mut,
        close = payer,
        has_one = mint,
        has_one = vault,
        has_one = payer,
        has_one = payee
    )]
    pub channel: Account<'info, ChannelAccount>,

    /// CHECK: Address constrained by has_one; receives channel/vault rent.
    #[account(mut)]
    pub payer: UncheckedAccount<'info>,

    /// CHECK: Address constrained by has_one; token ownership is checked below.
    pub payee: UncheckedAccount<'info>,

    pub mint: Account<'info, Mint>,

    #[account(mut, token::mint = mint, token::authority = channel)]
    pub vault: Account<'info, TokenAccount>,

    #[account(mut, token::mint = mint, token::authority = payer)]
    pub payer_token: Account<'info, TokenAccount>,

    #[account(mut, token::mint = mint, token::authority = payee)]
    pub payee_token: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

pub fn handle_finalize_channel(ctx: Context<FinalizeChannel>) -> Result<()> {
    let channel = &ctx.accounts.channel;
    let now = Clock::get()?.unix_timestamp;
    let payer_may_finalize = channel.status == ChannelStatus::Closing
        && now >= channel.close_requested_at + i64::from(channel.grace_seconds);
    require!(
        ctx.accounts.caller.key() == channel.payee
            || (ctx.accounts.caller.key() == channel.payer && payer_may_finalize),
        VerifiedInferenceError::FinalizeNotAuthorized
    );
    require!(
        ctx.accounts.vault.amount == channel.deposit,
        VerifiedInferenceError::VaultBalanceMismatch
    );

    let payer = channel.payer;
    let payee = channel.payee;
    let channel_id = channel.channel_id;
    let bump = [channel.bump];
    let signer_seeds: &[&[u8]] = &[
        CHANNEL_SEED,
        payer.as_ref(),
        payee.as_ref(),
        channel_id.as_ref(),
        &bump,
    ];
    let signer = &[signer_seeds];

    if channel.settled > 0 {
        token::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.vault.to_account_info(),
                    mint: ctx.accounts.mint.to_account_info(),
                    to: ctx.accounts.payee_token.to_account_info(),
                    authority: ctx.accounts.channel.to_account_info(),
                },
                signer,
            ),
            channel.settled,
            ctx.accounts.mint.decimals,
        )?;
    }

    let refund = channel
        .deposit
        .checked_sub(channel.settled)
        .ok_or(VerifiedInferenceError::ArithmeticOverflow)?;
    if refund > 0 {
        token::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.vault.to_account_info(),
                    mint: ctx.accounts.mint.to_account_info(),
                    to: ctx.accounts.payer_token.to_account_info(),
                    authority: ctx.accounts.channel.to_account_info(),
                },
                signer,
            ),
            refund,
            ctx.accounts.mint.decimals,
        )?;
    }

    token::close_account(CpiContext::new_with_signer(
        ctx.accounts.token_program.key(),
        CloseAccount {
            account: ctx.accounts.vault.to_account_info(),
            destination: ctx.accounts.payer.to_account_info(),
            authority: ctx.accounts.channel.to_account_info(),
        },
        signer,
    ))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn voucher_layout_matches_http_client() {
        let channel = Pubkey::new_from_array([7; 32]);
        let message = voucher_message(&channel, 42, 1_700_000_000);
        assert_eq!(&message[0..32], channel.as_ref());
        assert_eq!(&message[32..40], &42u64.to_le_bytes());
        assert_eq!(&message[40..48], &1_700_000_000i64.to_le_bytes());
    }
}
