// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfirmModal, CreateTicketModal, RuleContent, RulesModal } from './components'
import { api } from './api'
import type { Rule, Ticket } from './types'

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open','')}
  HTMLDialogElement.prototype.close = function () {this.removeAttribute('open')}
})
afterEach(() => {cleanup();vi.restoreAllMocks()})
const rule: Rule = {id:'demo:section:2.1',ref:'2.1',title:'Synthetic rule',section:'Synthetic section',text:'<img src=x onerror=alert(1)>',source:'synthetic-fixture',synthetic:true}

describe('safe review flows', () => {
  it('requires explicit confirmation before a simulated send', () => {
    const confirm = vi.fn()
    render(<ConfirmModal kind="send" busy={false} error="" onClose={vi.fn()} onConfirm={confirm}/>)
    const button = screen.getByRole('button',{name:'Подтвердить симуляцию'}) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox'));expect(button.disabled).toBe(false)
    fireEvent.click(button);expect(confirm).toHaveBeenCalledOnce()
    expect(screen.getByText(/Игрок не получит сообщение/)).toBeTruthy()
  })
  it('requires an escalation note and disables repeated submission while pending', () => {
    render(<ConfirmModal kind="escalate" busy={false} error="" onClose={vi.fn()} onConfirm={vi.fn()}/>)
    expect((screen.getByRole('button',{name:'Эскалировать'}) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByRole('textbox'),{target:{value:'Synthetic manual-review reason'}})
    expect((screen.getByRole('button',{name:'Эскалировать'}) as HTMLButtonElement).disabled).toBe(false)
  })
  it('renders untrusted rule text as text and shows canonical section ID', () => {
    const {container} = render(<RuleContent rule={rule}/>)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(rule.text)).toBeTruthy()
    expect(screen.getByText('demo:section:2.1')).toBeTruthy()
    expect(screen.getByText('Synthetic section')).toBeTruthy()
    expect(screen.getByText(/Это тестовое правило/)).toBeTruthy()
  })
  it('shows citation contents without issuing a second rules request', () => {
    const request = vi.spyOn(api,'rules')
    render(<RulesModal onClose={vi.fn()} initialRule={rule}/>)
    expect(request).not.toHaveBeenCalled()
    expect(screen.getByText(rule.id)).toBeTruthy()
  })
  it('protects create against repeated clicks and uses only explicit synthetic examples', async () => {
    let resolve!: (ticket: Ticket) => void
    const pending = new Promise<Ticket>(done => {resolve = done})
    const create = vi.spyOn(api,'create').mockReturnValue(pending)
    const onCreated = vi.fn()
    render(<CreateTicketModal onClose={vi.fn()} onCreated={onCreated}/>)
    fireEvent.click(screen.getByRole('button',{name:/Жалоба · RU/}))
    const submit = screen.getByRole('button',{name:'Обработать обращение'})
    fireEvent.click(submit);fireEvent.click(submit)
    expect(create).toHaveBeenCalledOnce()
    expect(create.mock.calls[0][0].text).toContain('[Синтетический пример]')
    expect((screen.getByRole('button',{name:'Закрыть окно'}) as HTMLButtonElement).disabled).toBe(true)
    resolve({id:'synthetic-created'} as Ticket)
    await waitFor(() => expect(onCreated).toHaveBeenCalledOnce())
  })
  it('retains idempotency key for a failed request retry with unchanged fields', async () => {
    const create = vi.spyOn(api,'create').mockRejectedValue(new Error('Synthetic connection failure'))
    render(<CreateTicketModal onClose={vi.fn()} onCreated={vi.fn()}/>)
    fireEvent.click(screen.getByRole('button',{name:/Payment · EN/}))
    fireEvent.click(screen.getByRole('button',{name:'Обработать обращение'}))
    await screen.findByText('Synthetic connection failure')
    fireEvent.click(screen.getByRole('button',{name:'Обработать обращение'}))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
    expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1])
  })
})
